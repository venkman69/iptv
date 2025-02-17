from datetime import datetime
import json
from pathlib import Path
import shutil
import tempfile
import threading
from typing import List
import ipytv
import ipytv.exceptions
from ipytv.playlist import M3UPlaylist
from langcodes import Language
from pymediainfo import MediaInfo
import requests
from streamlit import audio
import iptvdb
from peewee import SqliteDatabase
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logging.basicConfig(filename="iptv_downloader.log",level = logging.INFO)
ipytv_logger = logging.getLogger("ipytv.channel")
ipytv_logger.disabled = True
ipytv_logger = logging.getLogger("ipytv.playlist")
ipytv_logger.disabled = True



class MyMediaInfo(object):
    def __init__(self, media_info:dict):
        self.media_info = media_info
        self.general = []
        self.video = []
        self.audio = []
        self.subtitles = []

        for track in media_info["tracks"]:
            if track["track_type"] == 'General':
                format = track.get("format")
                duration = track.get("duration","0")
                #convert duration seconds to hours and minutes
                duration = int(duration)/1000 # convert to seconds
                hours = int(duration // 3600)
                minutes = int((duration % 3600) // 60)
                hour_minute = f"{hours}:{minutes}"
                file_size = track.get("general_compliance","Element size -1").split()[2]
                file_size = int(file_size)
                if file_size == -1:
                    human_file_size = "Not Found"
                elif file_size < 1024:
                    human_file_size = f"{file_size} B"
                elif file_size < 1024**2:
                    human_file_size = f"{file_size/1024:.2f} KB"
                elif file_size < 1024**3:
                    human_file_size = f"{file_size/1024**2:.2f} MB"
                else:
                    human_file_size = f"{file_size/1024**3:.2f} GB"
                self.general.append({"format":format,
                    "duration":duration,
                    "hour_minute":hour_minute,
                    "file_size":file_size,
                    "human_file_size":human_file_size
                })

            elif track["track_type"] == 'Video':
                video_codec = track["internet_media_type"]
                width = track["width"]
                height = track["height"]
                if width < 1080:
                    resolution = "SD"
                elif width < 1920:
                    resolution = "HD"
                elif width < 3840:
                    resolution = "FHD"
                else:
                    resolution = "UHD"
                aspect_ratio = track["display_aspect_ratio"]
                self.video.append({"video_codec":video_codec,
                                   "width":width,
                                   "height":height,
                                   "resolution":resolution,
                                   "aspect_ratio":aspect_ratio})

            elif track["track_type"] == 'Audio':
                language = track["language"]
                audio_channels = track["channel_s"]
                self.audio.append({"language":language,"audio_channels":audio_channels})

            elif track["track_type"] == 'Text':
                language = track["language"]
                self.subtitles.append({"language":language})

            # elif track["track_type"] == 'Menu':
            #     self.menu = track
            # elif track["track_type"] == 'Other':
            #     self.other = track
            # else:
            #     print(f"Unknown track type: {track.track_type}")
    def __get_general(self):
        recs =[]
        for track in self.general:
            recs.append(f'Time:{track["hour_minute"]} Size:{track["human_file_size"]}')
        return " | ".join(recs)
    
    def __get_video(self):
        recs = []
        for track in self.video:
            recs.append(f"Quality: {track['resolution']} WxH:{track['width']}x{track['height']}")
        return " | ".join(recs)
    def __get_audio(self):
        recs = []
        for track in self.audio:
            lang = Language.get(track['language']).display_name()
            recs.append(f"Channels: {track['audio_channels']} Lang:{lang}")
        return " | ".join(recs)
    def __get_subtitles(self):
        recs = []
        for track in self.subtitles:
            lang = Language.get(track['language']).display_name()
            recs.append(f"Lang:{lang}")
        return " | ".join(recs)

    def to_dict(self):
        data = {"general":self.__get_general(),
                "video":self.__get_video(),
                "audio":self.__get_audio(),
                "subtitles":self.__get_subtitles()
                }
        return data

def get_media_info(url)->MyMediaInfo:
    vid_stream_data, was_created=iptvdb.VideoStreamTbl.get_or_create(url=url)
    if was_created:
        with requests.get(url, stream=True,headers={'User-Agent':"Chrome"}) as r:
            r.raise_for_status()
            chunk = r.raw.read(8192*2)
            with tempfile.NamedTemporaryFile(prefix="x") as tmpfile:
                with open(tmpfile.name, 'wb') as f:
                    f.write(chunk)
                media_info = MediaInfo.parse(tmpfile.name)
                media_json=media_info.to_json() # this is a string
                vid_stream_data.media_info_json_str=media_json
                vid_stream_data.save()

                minfo= MyMediaInfo(json.loads(media_json))
                return minfo
    else:
        return MyMediaInfo(vid_stream_data.get_media_info_json())

# declare media_type as an enum with MOVIE and TV_SERIES as members
class media_type:
    MOVIE = "movie"
    TV_SERIES = "tv_series"
    LIVETV="liveTV"

def construct_m3u_url(site:str, username:str, password:str):
    """construct a URL for an M3U file from the site, username and password.

    Args:
        site (str): example http://tvportal.in:8000
        username (str): username
        password (str): password

    Returns:
        _type_: _description_
    """

    url_option= f"{site}/get.php?username={username}&password={password}&type=m3u_plus&output=ts"
            #  f"{site}/get.php?username={username}&password={password}&type=m3u&output=mpegts"
                #  ]
    return url_option

def read_m3u(m3u_url:str)->M3UPlaylist: #->List[iptvdb.IPTVTbl]: 
    """Reads an extended M3U file and returns a list of media entries."""
    media_list = []
    try:
        with tempfile.NamedTemporaryFile(prefix="vod") as tmpfile:
            download_regular_file(tmpfile.name, m3u_url)
            m3u_playlist:M3UPlaylist = ipytv.playlist.loadf(tmpfile.name)
            # m3u_json = json.loads(m3u_playlist.to_json_playlist())
            return m3u_playlist
            for item in m3u_playlist:
                rec = iptvdb.IPTVTbl()
                rec.get_from_m3u_channel_object(item, m3u_url)
                media_list.append(rec)
            return media_list
    except Exception as e:
        print(e)
        raise e
    raise Exception("Failed to read M3U file")

    # with open(file_path, 'r', encoding='utf-8') as f:
    #     group_uri = False
    #     line_count=0
    #     for line in f:
    #         line_count+=1
    #         line = line.strip()
    #         if line.startswith('#EXTM3U'):
    #             continue
    #         elif line.startswith('#EXTINF:'):
    #             if "####" in line:
    #                 current_group = line.split()[1]
    #                 group_uri = True
    #                 continue
    #             parts = line[8:].split(',', 1)
    #             duration = float(parts[0])
    #             #using re match a 2 or 3 letter language then hyphen then title
    #             lang_title = parts[1].strip()[:6].split('-', 1)
    #             if len(lang_title) == 2:
    #                 lang_field = lang_title[0].strip()
    #                 if (len(lang_field) == 2 or len(lang_field) == 3) and lang_field.isalpha():
    #                     lang = lang_title[0].strip()
    #                 # lang = lang_title[0].strip()
    #                     title = parts[1].strip().split('-',1)[1].strip()
    #             else:
    #                 lang = ""
    #                 title = parts[1].strip()
    #             current_entry:m3u = m3u(title=title, lang=lang, group=current_group)
    #         elif line:
    #             if group_uri:
    #                 group_uri = False
    #                 continue
    #             current_entry.url = line
    #             if "movie" in line:
    #                 current_entry.media_type = media_type.MOVIE
    #             elif "series" in line:
    #                 current_entry.media_type = media_type.TV_SERIES
                
    #             current_entry.line_count = line_count
    #             media_list.append(current_entry)
    #             current_entry = {}
    # return media_list

def update_iptvdb_tbl(provider_base_url:str,username:str, password:str):
    """Updates iptvd database with the contents of an M3U file from url

    Args:
        provider_base_url (str): iptv provider 
        username (str): _description_
        password (str): _description_

    Raises:
        e: _description_
    """

    m3u_url = construct_m3u_url(provider_base_url, username, password)
    try:
        media_list:M3UPlaylist = read_m3u(m3u_url)
        for chan in media_list:
            chan.attributes["provider"] = provider_base_url
    except ipytv.exceptions.URLException as e:
        print(e)
        print("Failed to read m3u file")
        raise e
    except Exception as e:
        print("Unknown error",e)
        raise e

    write_lock = threading.Lock()
    if iptvdb.IPTVProviderTbl.select().where(iptvdb.IPTVProviderTbl.provider == provider_base_url).count() == 0:
        with write_lock:
            iptvdb.IPTVProviderTbl.create(provider=provider_base_url,
                                          m3u_url=m3u_url, 
                                          last_updated=datetime.now(),
                                          enabled=True)
    # select records where provider is iptv_provider
    first_run = iptvdb.IPTVTbl.select().where(iptvdb.IPTVTbl.provider == provider_base_url).count( ) == 0
    
    if first_run:
        records=[]
        for item in media_list:
            iptvobj = iptvdb.IPTVTbl()
            iptvobj.get_from_m3u_channel_object(item)
            records.append(iptvobj)
        with write_lock:
            iptvdb.IPTVTbl.bulk_create(records, batch_size=10000)
    else:
        records=[]
        existing_urls = [rec.url for rec in iptvdb.IPTVTbl.select(iptvdb.IPTVTbl.url) ]
        item_dict = {item.url: item for item in media_list}
        to_be_created=set(item_dict.keys()) - set(existing_urls)
        to_be_deleted=set(existing_urls) - set(item_dict.keys())
        for key in to_be_created:
            item = item_dict[key]
            records.append(iptvdb.IPTVTbl(url=item.url, title=item.title, original_title=item.original_title, lang=item.lang, group=item.group, duration=item.duration, line_count=item.line_count, media_type=item.media_type))
        with write_lock:
            iptvdb.IPTVTbl.bulk_create(records, batch_size=10000)
            iptvdb.IPTVTbl.delete().where(iptvdb.IPTVTbl.url.in_(to_be_deleted)).execute()

def download_large_file(target_file_name:str, url:str):
    """ THis is a generator object to show progress
    cannot be used by itself without being in an iterator loop
    """
    with requests.get(url, stream=True,headers={'User-Agent':"Chrome"}) as r:
        chunk_size = 1024 * 1024
        r.raise_for_status()
        file_size = r.headers["Content-Length"]
        # extract the file name from the url
            # Process the streamed data (e.g., save to file)
        with open(target_file_name, 'wb') as f:
            chunks = int(int(file_size) // chunk_size)
            chunk_count = 0
            for chunk in r.iter_content(chunk_size=chunk_size):
                chunk_count+=1
                prog= chunk_count/chunks
                if prog > 1: prog = 1
                yield prog
                f.write(chunk)
    
def download_regular_file(target_file_name:str, url:str):
    resp = requests.get(url, headers={'User-Agent':"Chrome"})
    resp.raise_for_status()
    with open(target_file_name, 'wb') as f:
        f.write(resp.content)
        print(f"finished")

def download_regular_file_mock(target_file_name:str, url:str):
    #mock it with the vod.m3u file
    shutil.copyfile("vod10001.m3u", target_file_name)
    print("mock file used")

if __name__ == '__main__':
    WORK_DIR="./work"
    DATABASE = Path(WORK_DIR)/"iptv.db"
    sqldb = SqliteDatabase(DATABASE)
    iptvdb.db_proxy.initialize(sqldb)
    iptvdb.create_all()
    # http://tvstation.cc/get.php?username=TFFR5GY&password=NCW4K8P&type=m3u&output=mpegts
    
    # try:
    #     media = read_m3u("http://tvstation.cc", "TFFR5GY", "NCW4K8P")
    # except ipytv.exceptions.URLException as e:
    #     print(e)
    #     print("Failed to read m3u file")
    #     exit(1)
    update_iptvdb_tbl("http://tvstation.cc","TFFR5GY", "NCW4K8P")
