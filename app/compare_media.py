import json
from pathlib import Path
from pymediainfo import MediaInfo
import sys
from prettytable import PrettyTable
from utils import MyMediaInfo
from diskcache import Cache

dc = Cache("work/media_info")

def get_media_info(filename,ignore_cache:bool=False):
    if ignore_cache==False:
        myminfo_dict = dc.get(filename,None)
        if myminfo_dict:
            print("returning cached")
            return myminfo_dict
    file_size = Path(filename).stat().st_size
    minfo=MediaInfo.parse(filename)
    minfo_json_str = minfo.to_json()
    myminfo = MyMediaInfo(json.loads(minfo_json_str),file_size)
    myminfo_dict = myminfo.to_dict()
    myminfo_dict["filename"]=filename
    dc.set(filename, myminfo_dict)
    return myminfo_dict

if __name__=="__main__":
    if len(sys.argv) != 3:
        print("needs two filenames")
        print(sys.argv)
    file_a=get_media_info(sys.argv[1])
    file_b=get_media_info(sys.argv[2])
    
    tbl = PrettyTable()
    tbl.field_names=["Item","FileA","FileB"]
    tbl._max_width={"Item":8,"FileA":40,"FileB":40}
    for key,value in file_a.items():
        tbl.add_row([key,value,file_b[key]])
    print(tbl)