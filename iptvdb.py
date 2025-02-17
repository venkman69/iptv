from ast import For
from enum import unique
from peewee import (SqliteDatabase, BooleanField, CharField, DatabaseProxy, DateTimeField,
                    IntegerField, Model, Database, ForeignKeyField)
import requests
from ipytv.channel import IPTVChannel
from langcodes import *

rootLogger = None # to be furnished with logger
db_proxy:Database = DatabaseProxy()
class BaseModel(Model):
    class Meta:
        database = db_proxy

def create_all():
    db_proxy.create_tables([IPTVTbl, VideoStreamTbl, HistoryTbl, IPTVProviderTbl])

class IPTVProviderTbl(BaseModel):
    provider = CharField(primary_key=True)
    m3u_url = CharField(unique=True)
    last_updated = DateTimeField(null=True)
    enabled = BooleanField(default=True)


class IPTVTbl(BaseModel):
    provider = ForeignKeyField(IPTVProviderTbl,field="provider", on_delete='CASCADE')
    url = CharField(unique=True)
    title = CharField(null=True)
    original_title = CharField(null=True)
    lang_abbr = CharField(null=True)
    lang_full = CharField(null=True)
    group = CharField(null=True)
    duration = IntegerField(null=True)
    media_type = CharField(null=True)
    logo = CharField(null=True) 

    def get_from_m3u_channel_object(self, channel_object:IPTVChannel):
        self.provider = channel_object.attributes.get("provider",None)
        if self.provider == None:
            raise ValueError("Provider not found")
        self.url = channel_object.url
        lang_check = channel_object.name[:5]
        self.lang_abbr = None
        self.title = channel_object.name.lower()
        self.original_title = channel_object.name
        if "-" in lang_check:
            split_title = channel_object.name.split("-",1)[0].strip()
            lang = split_title.strip()
            if Language.get(lang).is_valid():
            # if lang.isalpha() and (len(lang)==2 or len(lang)==3):
                self.lang_abbr = lang
                self.lang_full = Language.get(lang).display_name()
                self.original_title = channel_object.name.split("-",1)[1].strip()
                self.title = self.original_title.lower()

        self.group = channel_object.attributes.get("group-title",None)
        self.duration = channel_object.duration
        if "series" in self.url:
            self.media_type = "series"
        elif "movie" in self.url:
            self.media_type = "movie"
        else:
            self.media_type = "livetv"
        self.logo = channel_object.attributes.get("tvg-logo",None)

    # def get_from_json(self, channel_item):
    #     self.source = channel_item["source"]
    #     self.url = channel_item["url"]
    #     self.title = channel_item["title"]
    #     self.original_title = channel_item["original_title"]
    #     self.lang = channel_item["lang"]
    #     self.group = channel_item["group"]
    #     self.duration = channel_item["duration"]
    #     self.line_count = channel_item["line_count"]
    #     self.media_type = channel_item["media_type"]
    #     self.logo = channel_item["logo"]

    #     self.original_title = item_json.get("name",None)
    #     self.title = self.original_title.lower()
    #     self.url = item_json.get("url",None)
    #     if self.title==None or self.url == None:
    #         raise ValueError("Invalid M3U item")
    #     self.group = item_json.get("attributes",{}).get("group-title",None)
    #     if "series" in self.url:
    #         self.media_type = media_type.TV_SERIES
    #     elif "movie" in self.url:
    #         self.media_type = media_type.MOVIE
    #     else:
    #         self.media_type = media_type.LIVETV
    #     self.duration = float(item_json.get("duration",0))
    #     self.logo = item_json.get("attributes",{}).get("tvg-logo",None)

    # def get_from_m3u(self, m3u):
    #     self.source = m3u.source
    #     self.url = m3u.url
    #     self.title = m3u.title
    #     self.original_title = m3u.original_title
    #     self.lang = m3u.lang
    #     self.group = m3u.group
    #     self.duration = m3u.duration
    #     self.line_count = m3u.line_count
    #     self.media_type = m3u.media_type
    #     self.logo = m3u.logo

class VideoStreamTbl(BaseModel):
    # use the fields from MyMediaInfo
    url = ForeignKeyField(IPTVTbl, field="url", on_delete='CASCADE')
    format = CharField(null=True)
    duration = IntegerField(null=True)
    file_size = IntegerField(null=True)
    video_codec = CharField(null=True)
    resolution = CharField(null=True)
    audio_channels = IntegerField(null=True)
    language = CharField(null=True)
    subtitles = CharField(null=True)
    width = IntegerField(null=True)
    height = IntegerField(null=True)
    aspect_ratio = CharField(null=True)


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