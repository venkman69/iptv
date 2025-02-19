import json
from urllib.parse import urlparse
from peewee import (SqliteDatabase, BooleanField, CharField, DatabaseProxy, DateTimeField,
                    IntegerField, Model, Database, ForeignKeyField
                    )
from ipytv.channel import IPTVChannel
from langcodes import *
import logging


logger = logging.getLogger(__name__)

db_proxy:Database = DatabaseProxy()
class BaseModel(Model):
    class Meta:
        database = db_proxy

def create_all():
    db_proxy.create_tables([IPTVTbl, VideoStreamTbl, HistoryTbl, IPTVProviderTbl])

class IPTVProviderTbl(BaseModel):
    provider = CharField(primary_key=True)
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
        url = url.replace("{provider}", self.provider)
        if self.username:
            url = url.replace("{username}", self.username)
        if self.password:
            url = url.replace("{password}", self.password)
        return url
    def get_any_url(self,url):
        url = url.replace("{provider}", self.provider)
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
    provider = ForeignKeyField(IPTVProviderTbl,field="provider", on_delete='CASCADE')
    url = CharField(unique=True)
    title = CharField(null=True)
    original_title = CharField(null=True)
    group = CharField(null=True)
    duration = IntegerField(null=True)
    media_type = CharField(null=True)
    logo = CharField(null=True) 

    def get_from_m3u_channel_object(self, channel_object:IPTVChannel, provider:IPTVProviderTbl):
        self.provider = channel_object.attributes.get("provider",None)
        if self.provider == None:
            raise ValueError("Provider not found")
        #get provider object
        # parse the url and retrieve the filename from channel_object.url
        self.url = provider.tokenize_channel_url(channel_object.url)
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

class VideoStreamTbl(BaseModel):
    # use the fields from MyMediaInfo
    url = ForeignKeyField(IPTVTbl, field="url", on_delete='CASCADE')
    media_info_json_str = CharField(null=True)

    def save(self, *args, **kwargs):
        if type(self.media_info_json_str) == dict:
            self.media_info_json_str = json.dumps(self.media_info_json_str)
        super().save(*args, **kwargs) 
        
    def get_media_info_json(self)->dict:
        if type(self.media_info_json_str) == str:
            return json.loads(self.media_info_json_str)
        return self.media_info_json_str

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