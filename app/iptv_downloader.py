# this program will load an extended m3u playlist and display it using streamlit
# it will sort the contents by language and movies and tv series
# after user selects a movie it can download the movie to a file

from hashlib import sha256
import hashlib
from pathlib import Path
import re
import time
from typing import List

import streamlit as st
import pandas as pd
import os
import requests
import shutil
import utils
from utils import MyMediaInfo
from streamlit_option_menu import option_menu   # pip install streamlit-option-menu
from streamlit_autorefresh import st_autorefresh
import db.iptvdb as iptvdb
from peewee import SqliteDatabase
from playhouse.shortcuts import model_to_dict
from datetime import datetime
import logging

cfg = utils.get_config()
WORK_DIR=cfg["general"]["work_dir"]
if not os.path.exists(WORK_DIR):
    os.makedirs(WORK_DIR)
VOD_FILE = Path(WORK_DIR)/"vod.m3u"
DATABASE = Path(WORK_DIR)/"iptv.db"
sqldb = SqliteDatabase(DATABASE)
iptvdb.db_proxy.initialize(sqldb)
iptvdb.create_all()
log_dir = cfg["general"]["log_dir"]
logger = utils.config_logger("iptv_downloader.log",Path(log_dir))
logger.setLevel(logging.DEBUG)
logging.getLogger("peewee").disabled=True


MOVIE_DOWNLOAD_PATH= cfg["general"]["movie_download_path"]
SERIES_DOWNLOAD_PATH= cfg["general"]["series_download_path"]
if cfg.has_section("ai"):
    AI_TOKEN=cfg["ai"]["token"]


# show a pulldown menu with groups from media_list and for language and a search input text for title
st.set_page_config(page_title="IPTV Downloader", page_icon=":tv:", layout="wide")

st.title("IPTV Downloader")

auto_refresh_toggle=st.toggle("AutoRefresh")

tabs = ["Media Downloader","Download Progress", "History", "M3u Manager"]
tab_dl, tab_dl_mgr, tab_history, tab_m3u_mgr=st.tabs(tabs)

if not "mediatypes" in st.session_state:
    st.session_state.mediatypes = ["All"]+[rec.media_type for rec in iptvdb.IPTVTbl.select(iptvdb.IPTVTbl.media_type).distinct()]


# with st.sidebar:
with tab_dl:
    # Create Streamlit widgets for group and language selection, and title search
    stcol1, stcol2, stcol3, stcol4=st.columns(4)
    with stcol1:
        date_picker_toggle=st.toggle("Enable date")
        if date_picker_toggle:
            date_added_since = st.date_input("Date added is newer than: ",value="today")
        else:
            date_added_since= (1==1)
        
    with stcol2:
        providers =["All"] + [rec.provider_m3u_base for rec in iptvdb.IPTVProviderTbl.select()]
        selected_provider = st.selectbox("Select Provider",providers)
    with stcol3:
        selected_media_type = st.selectbox("Select Media Type", ["All", "movie", "series", "livetv"])
    with stcol4:
        # add a datepicker

        where_clauses = [(1==1)]
        if selected_provider != "All":
            where_clauses.append(( iptvdb.IPTVTbl.provider_m3u_base == selected_provider) )
        if selected_media_type != "All":
            where_clauses.append(( iptvdb.IPTVTbl.media_type == selected_media_type) )
        if date_picker_toggle:
            where_clauses.append((iptvdb.IPTVTbl.added_date >= date_added_since))
        if st.toggle("English Groups"):
            english_groups=True
            english_where_clause=iptvdb.IPTVTbl.group.contains("ENGLISH") | \
                           iptvdb.IPTVTbl.group.contains(" EN ") | \
                           iptvdb.IPTVTbl.group.in_([
            "VOD | IMDB TOP 500","SRS | UK SERIES [EN] ","SRS | NETFLIX [EN]",
            "SRS | ANIME [EN]","SRS | SERIES [EN]","SRS | CLASSIC SERIES [EN]"])
            group_select_obj= iptvdb.IPTVTbl.select(iptvdb.IPTVTbl.group).distinct().where(english_where_clause)
            groups= [rec.group for rec in group_select_obj]
        else:
            english_groups=False
            groups = [rec.group for rec in iptvdb.IPTVTbl.select(iptvdb.IPTVTbl.group).distinct().where(*where_clauses)]
        selected_group = st.selectbox("Select Group", ["All"] + groups)
    
    search_title = st.text_input("Search Title").lower()
    st.divider()
    where_clauses = [(1 == 1)]
    if selected_provider != "All":
        where_clauses.append((iptvdb.IPTVTbl.provider_m3u_base == selected_provider ))
    if selected_group != "All":
        where_clauses.append((iptvdb.IPTVTbl.group == selected_group ) )
    else:
        if english_groups:
            where_clauses.append(english_where_clause)
        
    if selected_media_type != "All":
        where_clauses.append((iptvdb.IPTVTbl.media_type == selected_media_type ) )
    if date_picker_toggle:
        where_clauses.append((iptvdb.IPTVTbl.added_date >= date_added_since))

    if search_title or selected_group != "All" or selected_media_type != "All" or selected_provider != "All" or date_added_since != (1==1):
        print(f"Provider: {selected_provider} selected_group: {selected_group}, search_title: {search_title}")
        # search_cache_key = sha256(f"{date_added_since}{selected_provider}{selected_group}{selected_media_type}{search_title}".encode()).hexdigest()
        # if st.session_state.get(search_cache_key):
        #     filtered_media = st.session_state[search_cache_key]
        # else:
        #     filtered_media = []
            
        search_words = search_title.split()
        for word in search_words:
            where_clauses.append((iptvdb.IPTVTbl.title.contains(word)))
            
        filtered_media = iptvdb.IPTVTbl.select().where(*where_clauses).order_by(iptvdb.IPTVTbl.title)
    
        # st.session_state[search_cache_key] = filtered_media
        if st.toggle("Debug SQL"):
            st.write(filtered_media)
        # display the records in filtered_media as a table
        if not filtered_media:
            st.write("No media found matching the selected criteria.")
            st.write(filtered_media)
        else:
            # filtered_media_df = pd.DataFrame([
            # {"Title": item.original_title, "Group": item.group, "Type": item.media_type, "URL": item.url}
            # for item in filtered_media
            # ])
            filtered_media_df = list(filtered_media.dicts())
            redacted_filtered_media=[]
            for item in filtered_media_df:
                rec = {k:v for k,v in item.items() if k in ["url","media_type","group","original_title","logo"]}
                # if the first 5 chars contain a - at the end such as ALB - or EN - strip this
                title = rec['original_title'].strip()
                try:
                    if "-" == title[4] or "-" == title[3]:
                        title = rec["original_title"].split("-",1)[1].strip()
                        # remove any string starting with [ and ending with ]
                        title = re.sub(r'\[.*?\]', '', title).strip()
                    else:
                        title = rec["original_title"].strip()
                except Exception as e:
                    logger.error(f"title[4] is throwing exception {title}")
                    title = rec["original_title"].strip()

                rec["title"] = title
                rec["original_title"] = f"https://www.imdb.com/find/?q={title}&ref_=nv_sr_sm"
                redacted_filtered_media.append(rec)
            filtered_media_df = pd.DataFrame(redacted_filtered_media)
            filtered_media_df["Download"] = False
            # reorder filtered_media_df column so that Download is at the beginning
            cols = ["Download","logo","original_title","group","media_type","url","title"]
            filtered_media_df = filtered_media_df[cols]

            # st.write(filtered_media_df)
            download_items_df = st.data_editor(filtered_media_df,
                                               column_config={"Download": st.column_config.CheckboxColumn(default=False),
                                                              "url": None,
                                                              "logo": st.column_config.ImageColumn(),
                                                              "original_title":st.column_config.LinkColumn(disabled=True,
                                                                                                          display_text=".*=(.*)&.*" 
                                                                                                           ),
                                                              "group":st.column_config.Column(disabled=True),
                                                              "media_type":st.column_config.Column(disabled=True),
                                                              "title":None
                                               },
                                               key="search_results")

            selected_items = download_items_df[download_items_df["Download"] == True]
            if selected_items.empty:
                st.write("No items selected")
            else:
                if "selected_items_details" in st.session_state:
                    # then only fetch items that are missing
                    selected_items_details = st.session_state.selected_items_details
                else:
                    selected_items_details = {}
                details=[]
                for item in selected_items.itertuples():
                    iptv_obj:iptvdb.IPTVTbl = iptvdb.IPTVTbl.get_or_none(iptvdb.IPTVTbl.url==item.url)
                    if item.url in selected_items_details:
                        media_info:MyMediaInfo = selected_items_details[item.url]
                    else:
                        media_info:MyMediaInfo = utils.get_media_info(item.url)
                        selected_items_details[item.url] = media_info
                    rec={"title":item.title+"/"+iptv_obj.get_target_filename()}
                    rec.update(media_info.to_dict())
                    details.append(rec)
                st.session_state["selected_item_details"]=selected_items_details
                show_details_df = pd.DataFrame(details)
                st.data_editor(show_details_df)

                if st.button("Add selected items to download queue"):
                    for item in selected_items.itertuples():
                        iptv_obj:iptvdb.IPTVTbl = iptvdb.IPTVTbl.get_or_none(iptvdb.IPTVTbl.url==item.url)
                        if iptv_obj:
                            created_date = datetime.now()
                            download_mgr_obj = iptvdb.DownloadQueueTbl.create(created_date = created_date,
                                                                            updated_date = created_date,
                                                                            url = iptv_obj.url,
                                                                                file_path = iptv_obj.get_target_filename(cfg),
                                                                                state = iptvdb.DownloadStates.PENDING )
                        else:
                            raise ValueError(f"IPTVTbl object not found for {item.url}")
                    st.write("Submitted dl queue")

                    # del st.session_state[search_cache_key]
                    selected_items = download_items_df[download_items_df["Download"] == True]
                    # print(download_items_df)
                    try:
                        for row in selected_items.itertuples():
                            row["Download"] = False
                    except Exception as e:
                        print(e)

        st.write("Enter a search title to filter the media list")

with tab_dl_mgr:
    st.header("Download manager")
    
    def load_pending_items():
        pending_items = list(iptvdb.DownloadQueueTbl.select().where(iptvdb.DownloadQueueTbl.state.in_([iptvdb.DownloadStates.PENDING, iptvdb.DownloadStates.IN_PROGRESS])).dicts())
        newlist = []
        for item in pending_items:
            rec = {k: v for k, v in item.items() if k != "url"}
            newlist.append(rec)
        return pd.DataFrame(newlist)
    
    dl_in_prog = load_pending_items()
    st.data_editor(dl_in_prog, key="dl_in_prog1")
    # def refresh_data():
    #     st.session_state.dl_in_prog = load_pending_items()
    
    # st.button("Refresh Now", on_click=refresh_data)
    if auto_refresh_toggle:
        st.write(datetime.now())
        st_autorefresh(interval=10 * 1000, key="data_refresh")

with tab_history:
    st.header("Download History")
    pending_items = list(iptvdb.DownloadQueueTbl.select().where(iptvdb.DownloadQueueTbl.state.in_([iptvdb.DownloadStates.COMPLETE,iptvdb.DownloadStates.FAILED])).order_by(iptvdb.DownloadQueueTbl.created_date.desc()).dicts())
    newlist=[]
    for item in pending_items:
        rec = {k:v for k,v in item.items() if k != "url"}
        newlist.append(rec)
    pd_pending=pd.DataFrame(newlist)
    st.data_editor(pd_pending)

with tab_m3u_mgr:
    st.header("M3U Manager")
    if "providers" not in st.session_state:
        # Logic to refresh providers
        st.session_state.providers = [rec.provider_m3u_base for rec in iptvdb.IPTVProviderTbl.select()]

    # Display the list of providers
    providers = st.session_state.get("providers", ["All"] + [rec.provider_m3u_base for rec in iptvdb.IPTVProviderTbl.select()])
    selected_provider = st.selectbox("Provider to Refresh",providers)
    st.write(f"Selected Provider: {selected_provider}")
    if st.button("Refresh"):
        # provider_info:iptvdb.IPTVProviderTbl= iptvdb.IPTVProviderTbl.get_or_none(iptvdb.IPTVProviderTbl.provider == selected_provider)
        with st.spinner():
            utils.update_iptvdb_tbl(selected_provider,None, None,None, st)
    
    st.divider()
    if "delproviders" not in st.session_state:
        # Logic to refresh providers
        st.session_state.delproviders = list(iptvdb.IPTVProviderTbl.select().dicts())
    delproviders = st.session_state.delproviders
    delprovider_df=pd.DataFrame(delproviders)
    delprovider_df["Delete"] = False
    selected_del_items_df=st.data_editor(delprovider_df , column_config={"Delete":st.column_config.CheckboxColumn(default=False)})
    selected_del_items = selected_del_items_df[selected_del_items_df["Delete"] == True]
    if selected_del_items.empty:
        st.write("Nothing is selected")
    elif len(selected_del_items)==1:
        selected_del_item_dict = selected_del_items.to_dict(orient='records')[0]
        provider = selected_del_item_dict['provider_site']
        st.write(f"Delete>>>:   {provider}")
        if st.button("Delete"):
            st.write("Deleting")
            provider_obj=iptvdb.IPTVProviderTbl.get_or_none(iptvdb.IPTVProviderTbl.provider_site==provider)
            provider_obj.delete_instance()
            del st.session_state['delproviders']


    st.divider()
    st.write("Add Provider")
    provider_site     = st.text_input("Provider Site (ex: http://tivistation.com)")
    provider_base_url = st.text_input("Provider Base URL (ex: http://tivistation.cc:80)")
    provider_username = st.text_input("Username")
    provider_password = st.text_input("Password")
    if st.button("Import Provider Playlist"):
        utils.update_iptvdb_tbl(provider_base_url,provider_site, provider_username,provider_password, st)
