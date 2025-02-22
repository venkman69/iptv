from configparser import ConfigParser
from datetime import datetime
import json
import multiprocessing
import multiprocessing.queues
from pathlib import Path
import shutil
import tempfile
import threading
import ipytv
import ipytv.exceptions
from ipytv.playlist import M3UPlaylist
from ipytv.channel import IPTVChannel
from langcodes import Language
from pymediainfo import MediaInfo
import requests
from streamlit import audio
import streamlit
import iptvdb
from peewee import SqliteDatabase
import logging
import time
from diskcache import Cache

currenttimemillis=lambda: int(round(time.time() * 1000))
dc = Cache("work/m3ucache")

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
# logging.basicConfig(filename="iptv_downloader.log",level = logging.INFO)
# configure log output to contain datetime, method and line number
formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s:%(funcName)s():%(lineno)i %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")
file_handler = logging.FileHandler('iptv_downloader.log')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

ipytv_logger = logging.getLogger("ipytv.channel")
ipytv_logger.disabled = True
ipytv_logger = logging.getLogger("ipytv.playlist")
ipytv_logger.disabled = True



class MyMediaInfo(object):
    def __init__(self, media_info:dict, content_length:int=-1):
        self.media_info = media_info
        self.general = []
        self.video = []
        self.audio = []
        self.subtitles = []

        for track in media_info["tracks"]:
            if track["track_type"] == 'General':
                format = track.get("format")
                duration = track.get("duration", "0")
                # convert duration seconds to hours and minutes
                duration = int(duration) / 1000  # convert to seconds
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
            lang = Language.get(track['language']).display_name()
            recs.append(f"({track['audio_channels']}:{lang})")
        return " | ".join(recs)
    def __get_subtitles(self):
        recs = []
        for track in self.subtitles:
            lang = Language.get(track['language']).display_name()
            recs.append(lang)
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
    provider_obj:iptvdb.IPTVProviderTbl = iptvdb.IPTVProviderTbl.get(iptvdb.IPTVProviderTbl.provider==iptv_obj.provider)
    vid_stream_data, was_created=iptvdb.VideoStreamTbl.get_or_create(url=url)
    authenticated_url=provider_obj.get_any_url(url)
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

def read_m3u(m3u_url:str, st:streamlit=None)->M3UPlaylist: #->List[iptvdb.IPTVTbl]: 
    """Reads an extended M3U file and returns a list of media entries."""
    media_list = []
    m3u_playlist, expire_time = dc.get(m3u_url,None, expire_time=True)
    if m3u_playlist:
        logger.info("Returning cached m3u_playlist")
        if st:
            st.write("Returning cached m3u_playlist")
        return m3u_playlist
    try:
        with tempfile.NamedTemporaryFile(prefix="vod") as tmpfile:
            logger.debug(f"Beginning download of m3u")
            if st:
                logger.debugst.write(f"Beginning download of m3u")
            download_regular_file(tmpfile.name, m3u_url)
            logger.debug(f"Completed download of m3u, Parsing m3u file")
            if st:
                logger.debugst.write(f"Completed download of m3u, Parsing m3u file")
            m3u_playlist:M3UPlaylist = ipytv.playlist.loadf(tmpfile.name)
            logger.debug(f"Completed parsing m3u file")
            if st:
                logger.debugst.write(f"Completed parsing m3u file")
            # m3u_json = json.loads(m3u_playlist.to_json_playlist())
            dc.set(key=m3u_url,value= m3u_playlist,expire=86400)
            return m3u_playlist
    except Exception as e:
        print(e)
        raise e
    raise Exception("Failed to read M3U file")


def update_iptvdb_tbl(provider_base_url:str,username:str, password:str, st:streamlit=None):
    """Updates iptvd database with the contents of an M3U file from url

    Args:
        provider_base_url (str): iptv provider 
        username (str): _description_
        password (str): _description_

    Raises:
        e: _description_
    """

    write_lock = threading.Lock()

    start=currenttimemillis()
    if iptvdb.IPTVProviderTbl.select().where(
        iptvdb.IPTVProviderTbl.provider == provider_base_url).count() == 0:
        with write_lock:
            provider_object:iptvdb.IPTVProviderTbl = iptvdb.IPTVProviderTbl.create(provider=provider_base_url,
                                        username=username, 
                                        password=password,
                                        last_updated=datetime.now(),
                                        enabled=True)
        logger.debug(f"Wrote Provider to table {provider_base_url}")
        if st:
            st.write(f"Wrote Provider to table {provider_base_url}")
    else:
        provider_object:iptvdb.IPTVProviderTbl=iptvdb.IPTVProviderTbl.get(iptvdb.IPTVProviderTbl.provider==provider_base_url)

    m3u_url = provider_object.get_m3u_url()
    logger.debug(f"Fetched m3u url {m3u_url}")
    if st:
        st.write(f"Fetched m3u url {m3u_url}")

    try:
        start=currenttimemillis()
        media_list:M3UPlaylist = read_m3u(m3u_url, st)
        finish=currenttimemillis()
        logger.debug(f"M3u fetch took {finish - start}ms")
        st.write(f"M3u fetch took {finish - start}ms")
        start=currenttimemillis()
        for chan in media_list:
            chan.attributes["provider"] = provider_base_url
        finish=currenttimemillis()
        logger.debug(f"Adding provider to all M3U Channels took {finish - start}ms")
        st.write(f"Adding provider to all M3U Channels took {finish - start}ms")
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
    first_run = iptvdb.IPTVTbl.select().where(iptvdb.IPTVTbl.provider == provider_base_url).count( ) == 0
    logger.debug(f"Checked if IPTVTbl has no records for this provider: {first_run}")
    st.write(f"Checked if IPTVTbl has no records for this provider: {first_run}")
    
    if first_run:
        records=[]
        counter=0

        # start=currenttimemillis()
        records = create_iptvdbtbl_objects_threaded(media_list, provider_object)
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
        
    else:
        records=[]
        logger.debug(f"IPTVTbl records exist, updating missing items")
        if st:
            st.write(f"IPTVTbl records exist, updating missing items")
        existing_urls = [rec.url for rec in iptvdb.IPTVTbl.select(iptvdb.IPTVTbl.url).where(iptvdb.IPTVTbl.provider==provider_base_url) ]
        item_dict = {}
        for item in media_list:
            if not ( "series" in item.url or "movie" in item.url):
                continue
            item_dict[provider_object.tokenize_channel_url(item.url)]=item
        to_be_created=set(item_dict.keys()) - set(existing_urls)
        to_be_deleted=set(existing_urls) - set(item_dict.keys())
        start=currenttimemillis()
        for key in to_be_created:
            item = item_dict[key]
            iptvobj=iptvdb.IPTVTbl()
            iptvobj.get_from_m3u_channel_object(item,provider_object)
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

def create_iptvdbtbl_objects_threaded(media_list: M3UPlaylist, provider_object):
    mp = multiprocessing.Pool()
    input_items = []
    records = []
    write_lock = threading.Lock()
    start = currenttimemillis()
    counter = 0

    def process_batch(batch):
        results = mp.map(threaded_iptvobj_creator, [(item, provider_object) for item in batch])
        with write_lock:
            iptvdb.IPTVTbl.bulk_create(results, batch_size=10000)
        # return results

    chunk=50000
    for item in media_list:
        if not ("series" in item.url or "movie" in item.url):
            continue
        input_items.append(item)
        if len(input_items) == chunk:
            counter+=1
            logger.debug(f"Processing block: {counter * chunk}")
            process_batch(input_items)
            input_items = []

    if input_items:
        process_batch(input_items)

    finish = currenttimemillis()
    logger.debug(f"Threaded create and write IPTVTbl records took {finish - start}ms")
    return records

def threaded_iptvobj_creator(args):
    item, provider_object = args
    iptvobj = iptvdb.IPTVTbl()
    iptvobj.get_from_m3u_channel_object(item, provider_object)
    # logger.debug(f"Created IPTVTbl object for {iptvobj.url}")
    return iptvobj

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
    resp = requests.get(url, headers={'User-Agent':"Chrome"},timeout=120)
    resp.raise_for_status()
    with open(target_file_name, 'wb') as f:
        f.write(resp.content)
        print(f"finished")

def download_regular_file_mock(target_file_name:str, url:str):
    #mock it with the vod.m3u file
    shutil.copyfile("vod.m3u", target_file_name)
    print("mock file used")

def get_config():
    cfg = ConfigParser()
    cfg.read("iptv_downloader.ini")
    return cfg

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