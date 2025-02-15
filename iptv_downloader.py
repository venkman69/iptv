# this program will load an extended m3u playlist and display it using streamlit
# it will sort the contents by language and movies and tv series
# after user selects a movie it can download the movie to a file

from hashlib import sha256
import hashlib
import re
import time
from typing import List

from numpy import empty
import streamlit as st
import pandas as pd
import os
import requests
import shutil
from util import *
from streamlit_option_menu import option_menu   # pip install streamlit-option-menu

VOD_FILE = "vod.m3u"

def download_file(target_file_name:str, url:str):
    with requests.get(url, stream=True,headers={'User-Agent':"Chrome"}) as r:
        r.raise_for_status()
        file_size = r.headers["Content-Length"]
        st.write(f"Downloading {target_file_name} of size {file_size} bytes")
        # extract the file name from the url
            # Process the streamed data (e.g., save to file)
        with open(target_file_name, 'wb') as f:
            chunks = int(file_size) // 8192
            dl_bar=st.progress(0)
            chunk_count = 0
            for chunk in r.iter_content(chunk_size=8192):
                chunk_count+=1
                prog= chunk_count/chunks
                if prog > 1: prog = 1
                dl_bar.progress(prog)
                f.write(chunk)
            # shutil.copyfileobj(r.raw, f)
# show a pulldown menu with groups from media_list and for language and a search input text for title
st.set_page_config(page_title="IPTV Downloader", page_icon=":tv:", layout="wide")

st.title("IPTV Downloader")

with st.sidebar:
    if st.button("Clear Cache"):
        st.cache_data.clear()
        print("Cache Cleared")
        del st.session_state["media_list"]
    m3u_url = st.text_input("Enter the URL of the m3u file")
    if st.button("Download m3u file"):
        download_file("vod.m3u", m3u_url)
        del st.session_state["media_list"]
        # with requests.get(m3u_url, stream=True,) as r:
        #     with open("vod.m3u", 'wb') as f:
        #         shutil.copyfileobj(r.raw, f)



@st.cache_data(persist="disk", max_entries=1)
def initialize(vod_file:str,vod_hash:str):
    print("reading m3u")
    media_list:List[m3u] =read_m3u(vod_file)
    groups = sorted(set(item.group for item in media_list if item.group is not None))
    languages = sorted(set(item.lang for item in media_list if item.lang is not None))
    return media_list, groups, languages


#get the sha256sum hash for vod.m3u
if not "media_list" in st.session_state:
    st.write("Reading m3u file")
    if not os.path.exists(VOD_FILE):
        st.write("No m3u file found")
        st.stop()
    with open("vod.m3u", "rb") as f:
        vod_hash = hashlib.file_digest(f,"sha256")
    vod_hash_str = vod_hash.hexdigest()
    media_list, groups, languages = initialize("vod.m3u",vod_hash_str)
    st.session_state.media_list = media_list
    st.session_state.groups = groups
    st.session_state.languages = languages
    st.session_state.vod_hash_str = vod_hash_str
    st.write("Done Reading m3u file")
else:
    media_list = st.session_state.media_list
    groups = st.session_state.groups
    languages = st.session_state.languages
    vod_hash_str = st.session_state.vod_hash_str
# Extract groups and languages from media_list

with st.sidebar:
    # Create Streamlit widgets for group and language selection, and title search
    selected_media_type = st.selectbox("Select Media Type", ["All", "Movie", "TV Series"])
    selected_group = st.selectbox("Select Group", ["All"] + groups)
    selected_language = st.selectbox("Select Language", ["All"] + languages)
    search_title = st.text_input("Search Title").lower()
if search_title:
    print(f"selected_group: {selected_group}, selected_language: {selected_language}, search_title: {search_title}")
    # Filter media_list based on user selections
    search_cache_key = sha256(f"{vod_hash_str}{selected_group}{selected_language}{selected_media_type}{search_title}".encode()).hexdigest()
    if st.session_state.get(search_cache_key):
        filtered_media = st.session_state[search_cache_key]
    else:
        filtered_media = []
        for item in media_list:
            if (selected_group == "All" or item.group == selected_group) and \
               (selected_media_type == "All" or item.media_type == selected_media_type) and \
               (selected_language == "All" or item.lang == selected_language):
                search_words = search_title.split()
                if all (word in item.title for word in search_words):
                    filtered_media.append(item)
            
        filtered_media = sorted(filtered_media)
        st.session_state[search_cache_key] = filtered_media

    if not filtered_media:
        st.write("No media found matching the selected criteria.")
    else:
        # Display filtered media list
        st.write("Filtered Media List:")
        # Display filtered media list as a table with download checkboxes
        filtered_media_langs = sorted(set(item.lang for item in filtered_media if item.lang is not None))

        selected_media_type = st.selectbox("Filter Languages", ["All"]+filtered_media_langs)
        item:m3u=None
        filtered_media_df = pd.DataFrame([
            {"Title": item.original_title,"Lang": item.lang, 
            "url": item.url, "Download": False}
            for item in filtered_media if item.lang == selected_media_type or selected_media_type == "All"
        ])

        download_items_df = st.data_editor(filtered_media_df, column_config={"Download": st.column_config.CheckboxColumn(default=False)})
        # show a list of selected items and offer a download start button
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
                details.append({"Title": item.Title, "format": media_info.format,
                                "duration":media_info.hour_minute,
                                    "file_size":media_info.human_file_size,
                                    "video_codec":media_info.video_codec,
                                    "resolution":media_info.resolution,
                                    "audio_channels":str(media_info.audio_channels),
                                    "language":media_info.language,
                                    "subtitles":media_info.subtitles,
                })

            st.session_state.selected_items_details = selected_items_details
            st.write(pd.DataFrame(details))
            if st.button("Download Selected Items"):
                # show a progress bar for each download
                empty_space = st.empty()
                with empty_space.container():
                    counter = 0
                    max = len(selected_items)
                    dl_progress = st.progress(0)
                    for item in selected_items.itertuples():
                        dl_progress.progress(counter / max)
                        # with st.spinner(f"Downloading {item.Title} {item.url}..."):
                        file_extn = item.url.split('.')[-1]
                        target_file_name = f"{item.Title}.{file_extn}"
                        download_file(target_file_name, item.url)
                        counter += 1
                        # Add your download logic here
                empty_space.empty()
                st.write(f"Download completed : {counter} items")


# # Add a submit button
# if st.button("Submit"):
#     for item in filtered_media:
#         if st.session_state.get(f"download_{item.title}"):
#             st.write(f"Downloading {item.title}...")
#             # Add your download logic here

