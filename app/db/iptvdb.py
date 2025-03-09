from configparser import ConfigParser
import json
from urllib.parse import urlparse
from peewee import (SqliteDatabase, BooleanField, CharField, DatabaseProxy, DateTimeField,
                    IntegerField, Model, Database, ForeignKeyField,
                    FloatField
                    )
from ipytv.channel import IPTVChannel
from langcodes import *
import logging
from pathlib import Path
from mnamer import target, setting_store, providers


logger = logging.getLogger(__name__)

db_proxy:Database = DatabaseProxy()
class BaseModel(Model):
    class Meta:
        database = db_proxy

def create_all():
    db_proxy.create_tables([IPTVTbl, VideoStreamTbl, HistoryTbl, IPTVProviderTbl,DownloadQueueTbl])

class IPTVProviderTbl(BaseModel):
    provider_site= CharField(null=True) # friendly name
    provider_m3u_base = CharField(primary_key=True)
    # m3u_url can contain tokens such as {username} and {password}
    m3u_url = CharField(null=True) 
    username = CharField(null=True)
    password = CharField(null=True)
    last_updated = DateTimeField(null=True)
    enabled = BooleanField(default=True)

    def __init__(self, *args, **kwargs):
        # define m3u_url statically
        super().__init__(*args, **kwargs)
        self.m3u_url= "{provider}/get.php?username={username}&password={password}&type=m3u_plus&output=ts"

    def get_m3u_url(self):
        url = self.m3u_url
        url = url.replace("{provider}", self.provider_m3u_base)
        if self.username:
            url = url.replace("{username}", self.username)
        if self.password:
            url = url.replace("{password}", self.password)
        return url
    def get_any_url(self,url):
        url = url.replace("{provider}", self.provider_m3u_base)
        if self.username:
            url = url.replace("{username}", self.username)
        if self.password:
            url = url.replace("{password}", self.password)
        return url
    def tokenize_channel_url(self,url):
        url = url.replace(self.username,"{username}")
        url = url.replace(self.password,"{password}")
        return url

class IPTVTbl(BaseModel):
    provider_m3u_base = ForeignKeyField(IPTVProviderTbl,field=IPTVProviderTbl.provider_m3u_base, on_delete='CASCADE')
    url = CharField(unique=True)
    title = CharField(null=True)
    original_title = CharField(null=True)
    group = CharField(null=True)
    duration = IntegerField(null=True)
    media_type = CharField(null=True)
    logo = CharField(null=True) 
    added_date = DateTimeField(null=True)

    def get_from_m3u_channel_object(self, channel_object:IPTVChannel, provider:IPTVProviderTbl):
        # self.provider_m3u_base = provider.provider_m3u_base
        self.provider_m3u_base = channel_object.attributes.get("provider",None)
        if self.provider_m3u_base == None:
            raise ValueError(f"Provider not supplied")
        self.added_date = channel_object.attributes.get("fetch_time",None)
        #get provider object
        # parse the url and retrieve the filename from channel_object.url
        self.url = self.provider_m3u_base.tokenize_channel_url(channel_object.url)
        self.title = channel_object.name.lower()
        self.original_title = channel_object.name
        self.group = channel_object.attributes.get("group-title",None)
        self.duration = channel_object.duration
        if "series" in channel_object.url:
            self.media_type = "series"
        elif "movie" in channel_object.url:
            self.media_type = "movie"
        else:
            self.media_type = "livetv"
        self.logo = channel_object.attributes.get("tvg-logo",None)
    
    def get_target_filename(self,cfg:ConfigParser):
        movie_path = cfg["general"]["movie_download_path"]
        series_path = cfg["general"]["series_download_path"]
        file_extn = self.url.split('.')[-1]
        if self.media_type == "movie":
            target_file_name = Path(movie_path) / f"{self.title}.{file_extn}"
        if self.media_type == "series":
            mnamer_settings =  setting_store.SettingStore()
            mnamer_object=target.Target(Path(f"{self.title}.{file_extn}"),mnamer_settings)
            hits =mnamer_object.query()
            # use the first hit
            for hit in hits:
                if hit.series == mnamer_object.metadata.series:
                    mnamer_object.metadata.title = hit.title
                    break
            series_name_dir = Path(series_path) / mnamer_object.metadata.series
            season_path = series_name_dir / f"Season {mnamer_object.metadata.season}"
            target_file_name = season_path / mnamer_object.destination
        return target_file_name
    
    
    def get_authenticated_url_old(self):
        provider_obj = IPTVProviderTbl.get_or_none(IPTVProviderTbl.provider_m3u_base==self.provider_m3u_base)
        if provider_obj:
            url = self.url.replace("{provider}", provider_obj.provider_m3u_base)
            url = url.replace("{username}", provider_obj.username)
            url = url.replace("{password}", provider_obj.password)
            return url
        else:
            raise ValueError(f"Provider {self.provider_m3u_base} not found")
    def get_authenticated_url(self):
        provider_obj = self.provider_m3u_base
        if provider_obj:
            url = self.url.replace("{provider}", provider_obj.provider_m3u_base)
            url = url.replace("{username}", provider_obj.username)
            url = url.replace("{password}", provider_obj.password)
            return url
        else:
            raise ValueError(f"Provider {self.provider_m3u_base} not found")


class VideoStreamTbl(BaseModel):
    # use the fields from MyMediaInfo
    url = ForeignKeyField(IPTVTbl, field=IPTVTbl.url, on_delete='CASCADE')
    media_info_json_str = CharField(null=True)

    def save(self, *args, **kwargs):
        if type(self.media_info_json_str) == dict:
            self.media_info_json_str = json.dumps(self.media_info_json_str)
        super().save(*args, **kwargs) 
        
    def get_media_info_json(self)->dict:
        if type(self.media_info_json_str) == str:
            return json.loads(self.media_info_json_str)
        return self.media_info_json_str

class DownloadQueueTbl(BaseModel):
    created_date = DateTimeField(null=True)
    updated_date = DateTimeField(null=True)
    url = ForeignKeyField(IPTVTbl, field=IPTVTbl.url, on_delete='CASCADE')
    file_path = CharField() #target file path
    state = CharField()  # one of ['pending', 'in_progress','complete','failed']
    progress = FloatField(null=True) # a percentage
    eta = IntegerField(null=True)  # number of seconds to completion
    failure_message=CharField(null=True) # if failed, cause of failure
    file_size = IntegerField(null=True) #filesize in bytes

class DownloadStates:
    PENDING="pending"
    IN_PROGRESS='in_progress'
    COMPLETE='complete'
    FAILED='failed'


class HistoryTbl(BaseModel):
    message = CharField()
    action = CharField()
    datetime = DateTimeField(null=True)

if __name__ == "__main__":
    from pathlib import Path
    WORK_DIR="./work"
    DATABASE = Path(WORK_DIR)/"iptv.db"
    sqldb = SqliteDatabase(DATABASE)
    db_proxy.initialize(sqldb)
    create_all()
    db_proxy.close()

    print("Database tables created.")