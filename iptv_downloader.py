# this program will load an extended m3u playlist and display it using streamlit
# it will sort the contents by language and movies and tv series
# after user selects a movie it can download the movie to a file

from hashlib import sha256
import hashlib
from pathlib import Path
import re
import time
from typing import List

from numpy import empty, where
import streamlit as st
import pandas as pd
import os
import requests
import shutil
from util import *
from streamlit_option_menu import option_menu   # pip install streamlit-option-menu
import iptvdb
from peewee import SqliteDatabase
from playhouse.shortcuts import model_to_dict

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

# with st.sidebar:
    # if st.button("Clear Cache"):
    #     st.cache_data.clear()
    #     print("Cache Cleared")
    #     del st.session_state["media_list"]
    # m3u_url = st.text_input("Enter the URL of the m3u file")
    # if st.button("Download m3u file"):
    #     dl_prog = st.progress(0)
    #     for prog in download_large_file(VOD_FILE, m3u_url):
    #         dl_prog.progress(prog)
    #     del st.session_state["media_list"]
        # with requests.get(m3u_url, stream=True,) as r:
        #     with open("vod.m3u", 'wb') as f:
        #         shutil.copyfileobj(r.raw, f)



tabs = ["Media Downloader", "M3u Manager"]
tab_dl, tab_m3u_mgr=st.tabs(tabs)

if not "mediatypes" in st.session_state:
    st.session_state.mediatypes = ["All"]+[rec.media_type for rec in iptvdb.IPTVTbl.select(iptvdb.IPTVTbl.media_type).distinct()]
if not "groups" in st.session_state:
    st.session_state.groups = [rec.group for rec in iptvdb.IPTVTbl.select(iptvdb.IPTVTbl.group).distinct()]

groups = st.session_state.groups

with st.sidebar:
    # Create Streamlit widgets for group and language selection, and title search
    providers =["All"] + [rec.provider for rec in iptvdb.IPTVProviderTbl.select()]
    selected_provider = st.selectbox("Select Provider",providers)
    selected_media_type = st.selectbox("Select Media Type", ["All", "movie", "series", "livetv"])
    where_clause = (1==1)
    if selected_provider != "All":
        where_clause = (where_clause & ( iptvdb.IPTVTbl.provider == selected_provider) )
    if selected_media_type != "All":
        where_clause = (where_clause & ( iptvdb.IPTVTbl.media_type == selected_media_type) )
    # groups = [rec.group for rec in iptvdb.IPTVTbl.select(iptvdb.IPTVTbl.group).distinct().where(
    #         (iptvdb.IPTVTbl.media_type==selected_media_type) & 
    #         ( iptvdb.IPTVTbl.provider == selected_provider)
    #     )]
    groups = [rec.group for rec in iptvdb.IPTVTbl.select(iptvdb.IPTVTbl.group).distinct().where(where_clause)]

    selected_group = st.selectbox("Select Group", ["All"] + groups)
    search_title = st.text_input("Search Title").lower()
with tab_dl:
    if search_title or selected_group != "All" or selected_media_type != "All":
        print(f"selected_group: {selected_group}, search_title: {search_title}")
        search_cache_key = sha256(f"{selected_group}{selected_media_type}{search_title}".encode()).hexdigest()
        if st.session_state.get(search_cache_key):
            filtered_media = st.session_state[search_cache_key]
        else:
            filtered_media = []
            prefilter = iptvdb.IPTVTbl.select()
            if selected_group != "All":
                prefilter = prefilter.where(iptvdb.IPTVTbl.group==selected_group)
            if selected_media_type != "All":
                prefilter = prefilter.where(iptvdb.IPTVTbl.media_type== selected_media_type)
            
            search_words = search_title.split()
            for word in search_words:
                prefilter = prefilter.where(iptvdb.IPTVTbl.title.contains(word))
                
            filtered_media = prefilter.order_by(iptvdb.IPTVTbl.title)
            st.session_state[search_cache_key] = filtered_media
        # display the records in filtered_media as a table
        if not filtered_media:
            st.write("No media found matching the selected criteria.")
            st.write(filtered_media)
        else:
            filtered_media_df = pd.DataFrame([
            {"Title": item.original_title, "Group": item.group, "Type": item.media_type, "URL": item.url}
            for item in filtered_media
            ])
            filtered_media_df["Download"] = False
            # reorder filtered_media_df column so that Download is at the beginning
            cols = ["Download"] + [col for col in filtered_media_df.columns if col != "Download"]
            filtered_media_df = filtered_media_df[cols]

            # st.write(filtered_media_df)
            download_items_df = st.data_editor(filtered_media_df, column_config={"Download": st.column_config.CheckboxColumn(default=False)})

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
                if item.URL in selected_items_details:
                    media_info:MyMediaInfo = selected_items_details[item.URL]
                else:
                    media_info:MyMediaInfo = get_media_info(item.URL)
                rec={"Title":item.Title}
                rec.update(media_info.to_dict())
                details.append(rec)
            show_details_df = pd.DataFrame(details)
            st.data_editor(show_details_df)

            if st.button("Download Selected Items"):
                # show a progress bar for each download
                empty_space = st.empty()
                with empty_space.container():
                    counter = 0
                    max = len(selected_items)
                    dl_progress = st.progress(0)
                    for item in selected_items.itertuples():
                        dl_progress.progress(counter / max)
                        iptv_obj:iptvdb.IPTVTbl = iptvdb.IPTVTbl.get(iptvdb.IPTVTbl.url==item.URL)
                        provider_obj:iptvdb.IPTVProviderTbl = iptvdb.IPTVProviderTbl.get(iptvdb.IPTVProviderTbl.provider==iptv_obj.provider)
                        authenticated_url=provider_obj.get_any_url(item.URL)
                        st.write(f"Downloading {item.Title} {authenticated_url}...")
                        file_extn = item.URL.split('.')[-1]
                        if iptv_obj.media_type == "movie":
                            target_file_name = Path(MOVIE_DOWNLOAD_PATH) / f"{item.Title}.{file_extn}"
                        if iptv_obj.media_type == "series":
                            target_file_name = Path(SERIES_DOWNLOAD_PATH) / f"{item.Title}.{file_extn}"
                        
                        if target_file_name.exists():
                            st.write(f"Not Downloading {item.Title} as Target file exists: {target_file_name}")
                        else:
                            file_dl_progress= st.progress(0)
                            for prog in download_large_file(target_file_name, authenticated_url):
                                file_dl_progress.progress(prog)
                            counter += 1
                        # Add your download logic here
                empty_space.empty()
                st.write(f"Download completed : {counter} items")
    else:
        st.write("Enter a search title to filter the media list")

    # if not filtered_media:
    #     st.write("No media found matching the selected criteria.")
    # else:
    #     # Display filtered media list
    #     st.write("Filtered Media List:")
    #     # Display filtered media list as a table with download checkboxes
    #     filtered_media_langs = sorted(set(item.lang for item in filtered_media if item.lang is not None))

    #     selected_media_type = st.selectbox("Filter Languages", ["All"]+filtered_media_langs)
    #     item:m3u=None
    #     filtered_media_df = pd.DataFrame([
    #         {"Title": item.original_title,"Lang": item.lang, 
    #         "url": item.url, "Download": False}
    #         for item in filtered_media if item.lang == selected_media_type or selected_media_type == "All"
    #     ])

    #     download_items_df = st.data_editor(filtered_media_df, column_config={"Download": st.column_config.CheckboxColumn(default=False)})
    #     # show a list of selected items and offer a download start button
    #     selected_items = download_items_df[download_items_df["Download"] == True]
    #     if selected_items.empty:
    #         st.write("No items selected")
    #     else:
    #         if "selected_items_details" in st.session_state:
    #             # then only fetch items that are missing
    #             selected_items_details = st.session_state.selected_items_details
    #         else:
    #             selected_items_details = {}
    #         details=[]
    #         for item in selected_items.itertuples():
    #             if item.url in selected_items_details:
    #                 media_info:MyMediaInfo = selected_items_details[item.url]
    #             else:
    #                 media_info:MyMediaInfo = get_media_info(item.url)
    #                 selected_items_details[item.url] = media_info
    #             details.append({"Title": item.Title, "format": media_info.format,
    #                             "duration":media_info.hour_minute,
    #                                 "file_size":media_info.human_file_size,
    #                                 "video_codec":media_info.video_codec,
    #                                 "resolution":media_info.resolution,
    #                                 "audio_channels":str(media_info.audio_channels),
    #                                 "language":media_info.language,
    #                                 "subtitles":media_info.subtitles,
    #             })

    #         st.session_state.selected_items_details = selected_items_details
    #         st.write(pd.DataFrame(details))
    #         if st.button("Download Selected Items"):
    #             # show a progress bar for each download
    #             empty_space = st.empty()
    #             with empty_space.container():
    #                 counter = 0
    #                 max = len(selected_items)
    #                 dl_progress = st.progress(0)
    #                 for item in selected_items.itertuples():
    #                     dl_progress.progress(counter / max)
    #                     # with st.spinner(f"Downloading {item.Title} {item.url}..."):
    #                     file_extn = item.url.split('.')[-1]
    #                     target_file_name = f"{item.Title}.{file_extn}"
    #                     download_large_file(target_file_name, item.url)
    #                     counter += 1
    #                     # Add your download logic here
    #             empty_space.empty()
    #             st.write(f"Download completed : {counter} items")


# # Add a submit button
# if st.button("Submit"):
#     for item in filtered_media:
#         if st.session_state.get(f"download_{item.title}"):
#             st.write(f"Downloading {item.title}...")
#             # Add your download logic here

