import os
import time
import hashlib
import threading

class Hasher:
    """In the course of the admintool, we do a lot of md5 hashing of files.
    (The md5 is a database key.) We may have to check this hash every
    request. This can be expensive for large files.

    It is pretty safe to instead track files by (pathname, filesize, modtime).
    If all of those are the same, the file hasn't changed. So we're going
    to keep an (in-memory) cache mapping that tuple to md5.

    The AdminApp will keep a reference to this object. All methods must
    be thread-safe.
    """
    def __init__(self):
        self.map = {}
        
        # Any access to the map must be done under this lock.
        self.lock = threading.Lock()

    def get_md5(self, pathname):
        """Get an MD5 checksum from a file.
        We need the size for the cache lookup, so this just calls
        get_md5_size() and picks out the part we need.
        """
        md5, size = self.get_md5_size(pathname)
        return md5

    def get_size(self, pathname):
        """Get the size of a file. (This doesn't use the cache; it's
        here for completeness.)
        """
        stat = os.stat(pathname)
        return stat.st_size

    def get_md5_size(self, pathname):
        """Get both the MD5 checksum and the size for a file.
        """
        stat = os.stat(pathname)
        key = (pathname, stat.st_size, stat.st_mtime)
        now = time.time()
        
        with self.lock:
            ent = self.map.get(key)
            if ent is not None:
                ent.lastuse = now
                return ent.md5, ent.size

        # Gotta do this the hard way. Note that we do the md5 computation
        # *outside* the lock. There's a small chance that two threads will
        # start this work at the same time, but that's okay.

        hasher = hashlib.md5()
        fl = open(pathname, 'rb')
        while True:
            dat = fl.read(16384)
            if not dat:
                break
            hasher.update(dat)
        md5 = hasher.hexdigest()

        with self.lock:
            ### clean out old entries?
            # Another thread might have created an entry for this key;
            # we'll just replace it. It was identical anyhow.
            ent = MapEntry(key, now, md5)
            self.map[key] = ent
            return ent.md5, ent.size

class MapEntry:
    def __init__(self, key, now, md5):
        self.key = key
        self.md5 = md5
        self.size = key[1]
        self.lastuse = now
        
