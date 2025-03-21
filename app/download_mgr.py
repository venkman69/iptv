# this runs continuously in the background checking DownloadQueue
# if there is a new record then it starts processing it immediately one by one
# and in each step it updates the current state of the record
from datetime import datetime
import time
import db.iptvdb as iptvdb
import utils as utils
from peewee import SqliteDatabase
import logging
from pathlib import Path
currenttimemillis=lambda: int(round(time.time() * 1000))

cfg=utils.get_config()

log_dir = cfg["general"]["log_dir"]
logger = utils.config_logger("download_mgr.log",Path(log_dir))
logger.setLevel(logging.DEBUG)
logging.getLogger("peewee").disabled=True
#             "%(asctime)s %(levelname)s %(name)s:%(funcName)s():%(lineno)i %(message)s",
#                         datefmt="%Y-%m-%d %H:%M:%S")
# file_handler = logging.FileHandler('download_mgr.log')
# file_handler.setFormatter(formatter)
# logger.addHandler(file_handler)

def process_download_queue():
    pending_downloads = iptvdb.DownloadQueueTbl.select().where(iptvdb.DownloadQueueTbl.state == 'pending').order_by(iptvdb.DownloadQueueTbl.created_date)
    
    for download in pending_downloads:
        download:iptvdb.DownloadQueueTbl
        try:
            # Update the state to 'in_progress'
            download.state = iptvdb.DownloadStates.IN_PROGRESS
            download.updated_date = datetime.now()
            download.save()
            authenticated_url = download.url.get_authenticated_url()
            logger.info(f"Processing download for {download.file_path} URL: {authenticated_url}")
            eta = 0
            start = currenttimemillis()
            for prog in utils.download_large_file(download.file_path, authenticated_url):
                middle = currenttimemillis()
                speed = prog * 1000 / (middle - start) # % points per second
                remainder = 1- prog
                download.eta = remainder / speed # seconds
                download.progress = f"{prog * 100:.2f}"
                download.file_size=Path(download.file_path).stat().st_size
                download.updated_date = datetime.now()
                try:
                    download.save()
                    logger.info(f"Progress: {download.file_path} : {prog}")
                except:
                    pass

            finish=currenttimemillis() 
            # Update the state to 'complete'
            download.state = iptvdb.DownloadStates.COMPLETE
            download.progress = 100.0
            download.eta = (finish - start ) / 1000
            download.save()
            
            logger.info(f"Download complete for URL: {download.url.url} {download.file_path}")
        except Exception as e:
            # Update the state to 'failed' and set the failure message
            download.state = iptvdb.DownloadStates.FAILED
            download.failure_message = str(e)
            download.save()
            
            logger.error(f"Download failed for URL: {download.url.url} {download.file_path}, Error: {str(e)}")

if __name__ == "__main__":
    WORK_DIR="./work"
    DATABASE = Path(WORK_DIR)/"iptv.db"
    sqldb = SqliteDatabase(DATABASE)
    iptvdb.db_proxy.initialize(sqldb)
    iptvdb.create_all()
    
    # Process the download queue
    while True:
        process_download_queue()
        time.sleep(10)
    
    iptvdb.db_proxy.close()
    print("Database tables created.")