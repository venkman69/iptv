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
from util import *
from streamlit_option_menu import option_menu   # pip install streamlit-option-menu
from streamlit_autorefresh import st_autorefresh
import iptvdb
from peewee import SqliteDatabase
from playhouse.shortcuts import model_to_dict
from datetime import datetime

WORK_DIR="./work"
if not os.path.exists(WORK_DIR):
    os.makedirs(WORK_DIR)
VOD_FILE = Path(WORK_DIR)/"vod.m3u"
DATABASE = Path(WORK_DIR)/"iptv.db"
sqldb = SqliteDatabase(DATABASE)
iptvdb.db_proxy.initialize(sqldb)
iptvdb.create_all()
cfg = get_config()
MOVIE_DOWNLOAD_PATH= cfg["general"]["movie_download_path"]
SERIES_DOWNLOAD_PATH= cfg["general"]["series_download_path"]


# show a pulldown menu with groups from media_list and for language and a search input text for title
st.set_page_config(page_title="IPTV Downloader", page_icon=":tv:", layout="wide")

st.title("IPTV Downloader")


tabs = ["Media Downloader","Download Progress", "History", "M3u Manager"]
tab_dl, tab_dl_mgr, tab_history, tab_m3u_mgr=st.tabs(tabs)

if not "mediatypes" in st.session_state:
    st.session_state.mediatypes = ["All"]+[rec.media_type for rec in iptvdb.IPTVTbl.select(iptvdb.IPTVTbl.media_type).distinct()]
if not "groups" in st.session_state:
    st.session_state.groups = [rec.group for rec in iptvdb.IPTVTbl.select(iptvdb.IPTVTbl.group).distinct()]

groups = st.session_state.groups

# with st.sidebar:
with tab_dl:
    # Create Streamlit widgets for group and language selection, and title search
    stcol1, stcol2, stcol3=st.columns(3)
    with stcol1:
        providers =["All"] + [rec.provider_m3u_base for rec in iptvdb.IPTVProviderTbl.select()]
        selected_provider = st.selectbox("Select Provider",providers)
    with stcol2:
        selected_media_type = st.selectbox("Select Media Type", ["All", "movie", "series", "livetv"])
    with stcol3:
        where_clause = (1==1)
        if selected_provider != "All":
            where_clause = (where_clause & ( iptvdb.IPTVTbl.provider_m3u_base == selected_provider) )
        if selected_media_type != "All":
            where_clause = (where_clause & ( iptvdb.IPTVTbl.media_type == selected_media_type) )
        groups = [rec.group for rec in iptvdb.IPTVTbl.select(iptvdb.IPTVTbl.group).distinct().where(where_clause)]
        selected_group = st.selectbox("Select Group", ["All"] + groups)
    
    search_title = st.text_input("Search Title").lower()
    st.divider()
    where_clauses = [(1 == 1)]
    if selected_provider != "All":
        where_clauses.append((iptvdb.IPTVTbl.provider_m3u_base == selected_provider ))
    if selected_group != "All":
        where_clauses.append((iptvdb.IPTVTbl.group == selected_group ) )
    if selected_media_type != "All":
        where_clauses.append((iptvdb.IPTVTbl.media_type == selected_media_type ) )
    if search_title or selected_group != "All" or selected_media_type != "All" or selected_provider != "All":
        print(f"Provider: {selected_provider} selected_group: {selected_group}, search_title: {search_title}")
        search_cache_key = sha256(f"{selected_provider}{selected_group}{selected_media_type}{search_title}".encode()).hexdigest()
        if st.session_state.get(search_cache_key):
            filtered_media = st.session_state[search_cache_key]
        else:
            filtered_media = []
            
            search_words = search_title.split()
            for word in search_words:
                where_clauses.append((iptvdb.IPTVTbl.title.contains(word)))
                
            filtered_media = iptvdb.IPTVTbl.select().where(*where_clauses).order_by(iptvdb.IPTVTbl.title)
            st.session_state[search_cache_key] = filtered_media
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
                redacted_filtered_media.append(rec)
            filtered_media_df = pd.DataFrame(redacted_filtered_media)
            filtered_media_df["Download"] = False
            # reorder filtered_media_df column so that Download is at the beginning
            cols = ["Download","logo","original_title","group","media_type","url"]
            filtered_media_df = filtered_media_df[cols]

            # st.write(filtered_media_df)
            download_items_df = st.data_editor(filtered_media_df,
                                               column_config={"Download": st.column_config.CheckboxColumn(default=False),
                                                              "url":None,
                                                              "logo":st.column_config.ImageColumn()},
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
                if item.url in selected_items_details:
                    media_info:MyMediaInfo = selected_items_details[item.url]
                else:
                    media_info:MyMediaInfo = get_media_info(item.url)
                    selected_items_details[item.url] = media_info
                rec={"title":item.original_title}
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
                                                                            file_path = iptv_obj.get_target_filename(MOVIE_DOWNLOAD_PATH,SERIES_DOWNLOAD_PATH),
                                                                             state = iptvdb.DownloadStates.PENDING )
                    else:
                        raise ValueError(f"IPTVTbl object not found for {item.url}")
                st.write("Submitted dl queue")

                del st.session_state[search_cache_key]
                selected_items = download_items_df[download_items_df["Download"] == True]
                print(download_items_df)
                try:
                    for row in selected_items.itertuples():
                        row["Download"] = False
                except Exception as e:
                    print(e)

        st.write("Enter a search title to filter the media list")

with tab_dl_mgr:
    st.header("Download manager")
    auto_refresh_toggle=st.toggle("AutoRefresh")
    
    def load_pending_items():
        pending_items = list(iptvdb.DownloadQueueTbl.select().where(iptvdb.DownloadQueueTbl.state.in_([iptvdb.DownloadStates.PENDING, iptvdb.DownloadStates.IN_PROGRESS])).dicts())
        newlist = []
        for item in pending_items:
            rec = {k: v for k, v in item.items() if k != "url"}
            newlist.append(rec)
        return pd.DataFrame(newlist)
    
    if "dl_in_prog" not in st.session_state:
        st.session_state.dl_in_prog = load_pending_items()
    
    dl_in_prog = st.session_state.dl_in_prog
    
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
            update_iptvdb_tbl(selected_provider,None, None,None, st)
    
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
        update_iptvdb_tbl(provider_base_url,provider_site, provider_username,provider_password, st)
