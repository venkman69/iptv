from configparser import ConfigParser
from datetime import datetime
from importlib import metadata
import json
import math
import multiprocessing
import multiprocessing.queues
import os
import sys
from pathlib import Path
import shutil
import tempfile
import threading
from typing import Tuple
import ipytv
import ipytv.exceptions
from ipytv.playlist import M3UPlaylist
from ipytv.channel import IPTVChannel
import ipytv.playlist
from langcodes import Language
from pymediainfo import MediaInfo
import requests
from streamlit import audio
import streamlit
#from ..db import iptvdb 
from peewee import SqliteDatabase
import logging
import time
from diskcache import Cache
sys.path.append("/home/venkman/git/iptv/app")
import db.iptvdb as iptvdb
import shutil

currenttimemillis=lambda: int(round(time.time() * 1000))
dc = Cache("work/m3ucache")

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)
# # logging.basicConfig(filename="iptv_downloader.log",level = logging.INFO)
# # configure log output to contain datetime, method and line number
# formatter = logging.Formatter(
#             "%(asctime)s %(levelname)s %(name)s:%(funcName)s():%(lineno)i %(message)s",
#                         datefmt="%Y-%m-%d %H:%M:%S")
# file_handler = logging.FileHandler('iptv_downloader.log')
# file_handler.setFormatter(formatter)
# logger.addHandler(file_handler)

ipytv_logger = logging.getLogger("ipytv.channel")
ipytv_logger.disabled = True
ipytv_logger = logging.getLogger("ipytv.playlist")
ipytv_logger.disabled = True

def config_logger(log_file_name:str, log_file_dir:Path):
    log_file_dir.mkdir(parents=True,exist_ok=True)
    log_file_path = log_file_dir / log_file_name
    logging.basicConfig(
        level=logging.DEBUG,
        format= "%(asctime)s %(levelname)s %(name)s:%(funcName)s():%(lineno)i %(message)s",
        handlers=[
            logging.FileHandler(log_file_path)
        ]
    )
    return logging.getLogger(__name__)
    


class MyMediaInfo(object):
    def __init__(self, media_info:dict, content_length:int=-1):
        self.media_info = media_info
        self.general = []
        self.video = []
        self.audio = []
        self.subtitles = []

        for track in media_info.get("tracks"):
            if track["track_type"] == 'General':
                format = track.get("format")
                duration = track.get("duration", "0")
                # convert duration seconds to hours and minutes
                duration = int(float(duration)) / 1000  # convert to seconds
                hours = int(duration // 3600)
                minutes = int((duration % 3600) // 60)
                hour_minute = f"{hours:02}:{minutes:02}"
                if content_length > 0:
                    file_size = content_length
                else:
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
                video_codec = track.get("internet_media_type","-")
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
                language = track.get("language")
                audio_channels = track.get("channel_s")
                self.audio.append({"language": language, "audio_channels": audio_channels})

            elif track["track_type"] == 'Text':
                language = track.get("language")
                self.subtitles.append({"language": language})

            # elif track["track_type"] == 'Menu':
            #     self.menu = track
            # elif track["track_type"] == 'Other':
            #     self.other = track
            # else:
            #     print(f"Unknown track type: {track.track_type}")
    def __get_general(self):
        recs =[]
        for track in self.general:
            recs.append(f'{track["hour_minute"]} :{track["human_file_size"]}')
        return " | ".join(recs)
    
    def __get_video(self):
        recs = []
        for track in self.video:
            recs.append(f"{track['resolution']} WxH:{track['width']}x{track['height']}")
        return " | ".join(recs)
    def __get_audio(self):
        recs = []
        for track in self.audio:
            try:
                lang = Language.get(track['language']).display_name()
                recs.append(f"({track['audio_channels']}:{lang})")
            except:
                recs.append(f"({track['audio_channels']}:{track['language']})")
        return " | ".join(recs)
    def __get_subtitles(self):
        recs = []
        for track in self.subtitles:
            try:
                lang = Language.get(track['language']).display_name()
                recs.append(lang)
            except:
                recs.append(track['language'])
        return " | ".join(recs)

    def to_dict(self):
        data = {"general":self.__get_general(),
                "video":self.__get_video(),
                "audio":self.__get_audio(),
                "subtitles":self.__get_subtitles()
                }
        return data

def get_media_info(url)->MyMediaInfo:
    # read a 2MB chunk
    chunk_size = 1024 * 1024 * 2
    iptv_obj:iptvdb.IPTVTbl = iptvdb.IPTVTbl.get(iptvdb.IPTVTbl.url==url)
    # provider_obj:iptvdb.IPTVProviderTbl = iptvdb.IPTVProviderTbl.get(iptvdb.IPTVProviderTbl.provider_m3u_base==iptv_obj.provider_m3u_base)
    vid_stream_data, was_created=iptvdb.VideoStreamTbl.get_or_create(url=url)
    vid_stream_data:iptvdb.VideoStreamTbl
    authenticated_url=iptv_obj.get_authenticated_url()
    if not was_created and vid_stream_data.media_info_json_str == None:
        was_created=True
        # this will cause to refresh data if it is broken
        
    if was_created:
        with requests.get(authenticated_url, stream=True,headers={'User-Agent':"Chrome"}) as r:
            r.raise_for_status()
            chunk = r.raw.read(chunk_size)
            if 'content-length' in r.headers:
                content_length = int(r.headers['content-length'])
            else:
                content_length=-1
            with tempfile.NamedTemporaryFile(prefix="x") as tmpfile:
                with open(tmpfile.name, 'wb') as f:
                    f.write(chunk)
                media_info = MediaInfo.parse(tmpfile.name)
                media_json=media_info.to_json() # this is a string
                vid_stream_data.media_info_json_str=media_json
                vid_stream_data.save()

                minfo= MyMediaInfo(json.loads(media_json), content_length)
                return minfo
    else:
        return MyMediaInfo(vid_stream_data.get_media_info_json())

# declare media_type as an enum with MOVIE and TV_SERIES as members
class MediaType:
    MOVIE = "movie"
    TV_SERIES = "series"
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
def compare_vods(old_vod, new_vod):
    old_vod_map =read_vod_to_map(old_vod)
    new_vod_map =read_vod_to_map(new_vod)
    old_urls = set(old_vod_map.keys())
    new_urls = set(new_vod_map.keys())
    delta_new = new_urls - old_urls
    final_map={}
    for url in delta_new:
        final_map[url]=new_vod_map[url]
    new_lines=["#EXTM3U"]
    for k,v in final_map.items():
        new_lines.append(v)
        new_lines.append(k)
    return new_lines

def read_vod_to_map(vod_file:str)->dict:
    """Read the vod file to a map of url->extinfo 
    returns map,header
    skips live tv and keeps only series and movies
    """
    with open(vod_file) as f:
        vod=f.read()
    vod_lines = vod.split("\n")
    vod_url_map ={}
    for i in range(2,len(vod_lines),2):
        url = vod_lines[i]
        ext = vod_lines[i-1]
        if not ( "series" in url or "movie" in url):
            continue
        vod_url_map[url] = ext
    return vod_url_map

def read_m3u(m3u_url:str, st:streamlit=None)->dict: 
    """Reads an extended M3U file and retuns a url->extinfo map"""
    global WORK_DIR
    media_list = []
    # m3u_playlist, expire_time = dc.get(m3u_url,None, expire_time=True)
    # if m3u_playlist:
    #     logger.info("Returning cached m3u_playlist")
    #     if st:
    #         st.write("Returning cached m3u_playlist")
    #     return m3u_playlist
    try:
        with tempfile.NamedTemporaryFile(prefix="vod") as tmpfile:
            logger.debug(f"Beginning download of m3u")
            if st:
                st.write(f"Beginning download of m3u")
            download_regular_file(tmpfile.name, m3u_url)
            logger.debug(f"Completed download of m3u, reading into a map")
            if st:
                st.write(f"Completed download of m3u, reading into a map ")
            vodmap = read_vod_to_map(tmpfile.name)
            return vodmap
            shutil.copy(tmpfile.name, "./work/")
            logger.debug(f"Completed download of m3u, Parsing m3u file")
            if st:
                st.write(f"Completed download of m3u, Parsing m3u file")
                m3u_playlist:M3UPlaylist = ipytv.playlist.loadf(tmpfile.name)
            logger.debug(f"Completed parsing m3u file")
            if st:
                st.write(f"Completed parsing m3u file")
            # m3u_json = json.loads(m3u_playlist.to_json_playlist())
            return m3u_playlist
    except Exception as e:
        print(e)
        raise e
    raise Exception("Failed to read M3U file")


def update_iptvdb_tbl(provider_m3u_base:str, provider_site:str, username:str, password:str, st:streamlit=None):
    """Updates iptvd database with the contents of an M3U file from url

    Args:
        provider_site (str): iptv provider main site
        provider_base_url (str): iptv provider 
        username (str): _description_
        password (str): _description_

    Raises:
        e: _description_
    """
    write_lock = threading.Lock()
    fetch_time = datetime.now()
    start=currenttimemillis()
    provider_object:iptvdb.IPTVProviderTbl=iptvdb.IPTVProviderTbl.get_or_none(iptvdb.IPTVProviderTbl.provider_m3u_base==provider_m3u_base)
    if provider_object is None:
        with write_lock:
            provider_object:iptvdb.IPTVProviderTbl = iptvdb.IPTVProviderTbl.create(provider_m3u_base=provider_m3u_base)
            provider_object.provider_site=provider_site
            provider_object.username=username
            provider_object.password=password
            provider_object.last_updated=datetime.now()
            provider_object.enabled=True
            provider_object.save()

        logger.debug(f"Wrote Provider to table {provider_m3u_base}")
        if st:
            st.write(f"Wrote Provider to table {provider_m3u_base}")


    m3u_url = provider_object.get_m3u_url()
    logger.debug(f"Fetched m3u url {m3u_url}")
    if st:
        st.write(f"Fetched m3u url {m3u_url}")

    try:
        start=currenttimemillis()
        ext_map = read_m3u(m3u_url, st)
        # media_list:M3UPlaylist = read_m3u(m3u_url, st)
        finish=currenttimemillis()
        logger.debug(f"M3u fetch took {finish - start}ms")
        st.write(f"M3u fetch took {finish - start}ms")
        # start=currenttimemillis()
        # for chan in media_list:
        #     chan.attributes["provider"] = provider_m3u_base
        #     chan.attributes["fetch_time"] = fetch_time
        # finish=currenttimemillis()
        # logger.debug(f"Adding provider to all M3U Channels took {finish - start}ms")
        # st.write(f"Adding provider to all M3U Channels took {finish - start}ms")
    except ipytv.exceptions.URLException as e:
        print(e)
        st.write(e)
        print("Failed to read m3u file")
        st.write("Failed to read m3u file")
        raise e
    except Exception as e:
        print("Unknown error",e)
        raise e

    # select records where provider is iptv_provider
    first_run = iptvdb.IPTVTbl.select().where(iptvdb.IPTVTbl.provider_m3u_base == provider_m3u_base).count( ) == 0
    logger.debug(f"Checked if IPTVTbl has no records for this provider: {first_run}")
    st.write(f"Checked if IPTVTbl has no records for this provider: {first_run}")
    
    if first_run:
        records=[]
        counter=0

        # start=currenttimemillis()
        records = create_iptvdbtbl_objects_threaded(ext_map, provider_object, provider_m3u_base, fetch_time)
        #     chan.attributes["provider"] = provider_m3u_base
        #     chan.attributes["fetch_time"] = fetch_time
        finish=currenttimemillis()
        logger.debug(f"Finished writing in {(finish-start)}")
        st.write(f"Finished writing in {(finish-start)}")
        finish=currenttimemillis()
        logger.debug(f"Created list of IPTVTbl records, len:{len(records)}")
        st.write(f"Created list of IPTVTbl records, len:{len(records)}")
        start=currenttimemillis()
        finish=currenttimemillis()
        logger.debug(f"Executed bulk create IPTVTbl records:{finish-start}ms")
        if st:
            st.write(f"Executed bulk create IPTVTbl records:{finish-start}ms")
        provider_object.last_updated=datetime.now()
        provider_object.save()
        
    else:
        records=[]
        logger.debug(f"IPTVTbl records exist, updating missing items")
        if st:
            st.write(f"IPTVTbl records exist, updating missing items")
        existing_urls = [rec.url for rec in iptvdb.IPTVTbl.select(iptvdb.IPTVTbl.url).where(iptvdb.IPTVTbl.provider_m3u_base==provider_m3u_base) ]
        # tokenize the ext map urls
        # this has to be done here so url to url can be compared
        new_ext_map = {}
        for url in ext_map.keys():
            new_url=provider_object.tokenize_channel_url(url)
            new_ext_map[new_url]=ext_map[url]

        m3u_urls = set(new_ext_map.keys())
        to_be_created = m3u_urls - set(existing_urls)
        to_be_deleted = set(existing_urls) - m3u_urls
        to_be_created_ext=["#EXTM3U"]
        for url in to_be_created:
            to_be_created_ext.append(new_ext_map[url])
            to_be_created_ext.append(url)
        to_be_created_m3u = ipytv.playlist.loadl(to_be_created_ext)
        records=[]
        for item in to_be_created_m3u:
            iptvobj=iptvdb.IPTVTbl()
            iptvobj.get_from_m3u_channel_object(item,provider_object, fetch_time)
            records.append(iptvobj)
        with write_lock:
            iptvdb.IPTVTbl.bulk_create(records, batch_size=10000)
            logger.debug(f"Added rows: {len(records)}")
            if st:
                st.write(f"Added rows: {len(records)}")
        
        rows_deleted = iptvdb.IPTVTbl.delete().where(iptvdb.IPTVTbl.url << to_be_deleted).execute()
        logger.debug(f"Deleted rows: {rows_deleted}")
        if st:
            st.write(f"Deleted rows: {rows_deleted}")
        finish=currenttimemillis()
        logger.debug(f"Completed update of IPTVTbl in {finish-start}ms")
        if st:
            st.write(f"Completed update of IPTVTbl in {finish-start}ms")
        provider_object.last_updated=datetime.now()
        provider_object.save()

def chunk_url_to_m3u(url_to_exp:dict,chunksize:int):
    """This is an interator object that will produce chunksize items from the ext
    that is an M3uPlaylist object

    """
    chunk=["#EXTM3U"]
    keys = list(url_to_exp.keys())
    for i in range(len(keys)):
        # rebuild EXTINF and URL
        if not ("series" in keys[i] or "movie" in keys[i]):
            continue
        chunk.append(url_to_exp[keys[i]])
        chunk.append(keys[i])
        if len(chunk)/2 > chunksize:
            chunk_m3u = ipytv.playlist.loadl(chunk)
            yield chunk_m3u
            chunk=["#EXTM3U"]
    if len(chunk) > 1:
        chunk_m3u = ipytv.playlist.loadl(chunk)
        yield chunk_m3u



def create_iptvdbtbl_objects_threaded(media_map: dict, provider_object:iptvdb.IPTVProviderTbl,  provider_m3u_base:str, fetch_time:datetime):
    """media_map is url>extinfo dictionary"""     
    mp = multiprocessing.Pool()
    input_items = []
    records = []
    write_lock = threading.Lock()
    start = currenttimemillis()
    counter = 0

    def process_batch(batch):
        results = mp.map(threaded_iptvobj_creator, [(item, provider_object, fetch_time) for item in batch])
        with write_lock:
            iptvdb.IPTVTbl.bulk_create(results, batch_size=10000)
        # return results

    chunksize=50000
    urls_processed=set()
    for m3u_playlist_chunk in chunk_url_to_m3u(media_map, chunksize):
        counter+=1
        logger.debug(f"Processing block: {counter * chunksize}")
        process_batch(m3u_playlist_chunk)
        
    finish = currenttimemillis()
    logger.debug(f"Threaded create and write IPTVTbl records took {finish - start}ms")
    return records

def threaded_iptvobj_creator(args):
    item, provider_object, fetch_time= args
    provider_object:iptvdb.IPTVProviderTbl 
    iptvobj = iptvdb.IPTVTbl()
    iptvobj.get_from_m3u_channel_object(item, provider_object, fetch_time)
    # logger.debug(f"Created IPTVTbl object for {iptvobj.url}")
    return iptvobj

def download_large_file(target_file_name:str, url:str):
    """ THis is a generator object to show progress
    cannot be used by itself without being in an iterator loop
    """
    target_path = Path(target_file_name)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    
    with requests.get(url, stream=True,headers={'User-Agent':"Chrome"}) as r:
        chunk_size = 1024 * 1024
        r.raise_for_status()
        file_size = r.headers["Content-Length"]
        # extract the file name from the url
            # Process the streamed data (e.g., save to file)
        with open(target_file_name, 'wb') as f:
            chunks = int(int(file_size) // chunk_size)
            chunk_count = 0
            last_prog=0
            one_percent_chunks=math.ceil(chunks/100)
            for chunk in r.iter_content(chunk_size=chunk_size):
                chunk_count+=1
                prog= int(chunk_count/one_percent_chunks)
                if prog != last_prog:
                    last_prog = prog
                    if prog > 100: 
                        prog = 100
                    yield prog/100
                f.write(chunk)

def download_regular_file(target_file_name:str, url:str):

    resp = dc.get(url, None)
    if resp == None:
        resp = requests.get(url, headers={'User-Agent':"Chrome"},timeout=120)
        resp.raise_for_status()
        dc.set(key=url,value= resp,expire=21600) # 6hours
    else:
        logger.debug(f"Returning cached response for {url}")

    with open(target_file_name, 'wb') as f:
        f.write(resp.content)
        print(f"finished")

def download_regular_file_mock(target_file_name:str, url:str):
    #mock it with the vod.m3u file
    shutil.copyfile("vod.m3u", target_file_name)
    print("mock file used")

def get_config():
    if Path("config/iptv_downloader.ini").exists():
        cfg = ConfigParser()
        cfg.read("config/iptv_downloader.ini")
        return cfg
    else:
        raise FileNotFoundError(f"config/iptv_downloader.ini file not found at: {os.getcwd()}")




if __name__ == '__main__':
    WORK_DIR="./work"
    DATABASE = Path(WORK_DIR)/"iptv.db"
    sqldb = SqliteDatabase(DATABASE)
    iptvdb.db_proxy.initialize(sqldb)
    iptvdb.create_all()
    # http://tvstation.cc/get.php?username=TFFR5GY&password=NCW4K8P&type=m3u&output=mpegts
    
    # update_iptvdb_tbl("http://tvstation.cc","TFFR5GY", "NCW4K8P")
    # update_iptvdb_tbl("http://line.myox.me","3kgolbiu48", "6o6ivdhzer")
# http://line.myox.me/get.php?username=3kgolbiu48&password=6o6ivdhzer&type=m3u_plus&output=ts
    # update_iptvdb_tbl("http://tvportal.in:8000", "KS7RDDfvd9","Tx4zYhYY4q")

    media_info = MediaInfo.parse('minfo')
    print(media_info.audio_tracks[0])
    print(media_info.video_tracks[0])
