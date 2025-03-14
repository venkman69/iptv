
# IPTV Downloader

This is to harvest m3u playlist for movies and series and allow a search and download UI.


# iptv notes
url  for clientarea.4kvod.eu is like so: tvportal.in:8000 user pass


# semlock issue
Error looks like so

```
                  ^^^^^^^^^^
  File "/usr/lib/python3.12/multiprocessing/context.py", line 68, in Lock
    return Lock(ctx=self.get_context())
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/multiprocessing/synchronize.py", line 169, in __init__
    SemLock.__init__(self, SEMAPHORE, 1, 1, ctx=ctx)
  File "/usr/lib/python3.12/multiprocessing/synchronize.py", line 57, in __init__
    sl = self._semlock = _multiprocessing.SemLock(
                         ^^^^^^^^^^^^^^^^^^^^^^^^^
PermissionError: [Errno 13] Permission denied
```

wsl /dev/shm is read only
Set this to write by all in /etc/fstab
```
none /dev/shm tmpfs defaults,size=8G,mode=777        0 0
```

