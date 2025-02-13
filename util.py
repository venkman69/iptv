import pprint
import re

# declare media_type as an enum with MOVIE and TV_SERIES as members
class media_type:
    MOVIE = "movie"
    TV_SERIES = "tv_series"


class m3u(object):
    # define class attributes
    title:str = None
    original_title:str = None
    lang:str = None
    group:str = None
    url:str = None
    duration:float = None
    line_count:int= None
    media_type = None

    def __init__(self, title:str, url:str=None, line_count:int=None, lang:str=None, group:str=None,  duration:float=None, media_type:str=None):
        self.title:str = title.lower()
        self.original_title:str = title.strip()
        self.url:str = url
        self.line_count = line_count
        if lang:
            self.lang:str = lang.lower()
        if group:
            self.group:str = group.lower()
        if duration:
            self.duration:float = duration
        if media_type:
            self.media_type:str = media_type.lower()
    def __lt__(self, other):
        return self.title < other.title


def read_m3u(file_path):
    """Reads an extended M3U file and returns a list of media entries."""
    media_list = []
    current_entry = {}
    current_group= None
    duration=None
    line_count=None

    with open(file_path, 'r', encoding='utf-8') as f:
        group_uri = False
        line_count=0
        for line in f:
            line_count+=1
            line = line.strip()
            if line.startswith('#EXTM3U'):
                continue
            elif line.startswith('#EXTINF:'):
                if "####" in line:
                    current_group = line.split()[1]
                    group_uri = True
                    continue
                parts = line[8:].split(',', 1)
                duration = float(parts[0])
                #using re match a 2 or 3 letter language then hyphen then title
                lang_title = parts[1].strip()[:6].split('-', 1)
                if len(lang_title) == 2:
                    lang_field = lang_title[0].strip()
                    if (len(lang_field) == 2 or len(lang_field) == 3) and lang_field.isalpha():
                        lang = lang_title[0].strip()
                    # lang = lang_title[0].strip()
                        title = parts[1].strip().split('-',1)[1].strip()
                else:
                    lang = ""
                    title = parts[1].strip()
                current_entry:m3u = m3u(title=title, lang=lang, group=current_group)
            elif line:
                if group_uri:
                    group_uri = False
                    continue
                current_entry.url = line
                if "movie" in line:
                    current_entry.media_type = media_type.MOVIE
                elif "series" in line:
                    current_entry.media_type = media_type.TV_SERIES
                
                current_entry.line_count = line_count
                media_list.append(current_entry)
                current_entry = {}
    return media_list

if __name__ == '__main__':
    media = read_m3u("vod.m3u")
    for rec in media:
        if "mandalorian" in rec.title and rec.lang == "en":
            print(rec.line_count, rec.title, rec.lang, rec.url)