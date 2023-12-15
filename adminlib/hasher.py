import os
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
        # Any access to the map must be done under this lock.
        self.lock = threading.Lock()

    def get_md5_size(self, pathname):
        """Get both the MD5 checksum and the size for a file.
        """
        size = self.get_size(pathname)
        md5 = self.get_md5(pathname)
        return (md5, size)

    def get_md5(self, pathname):
        """Get an MD5 checksum from a file.
        """
        hasher = hashlib.md5()
        fl = open(pathname, 'rb')
        while True:
            dat = fl.read(16384)
            if not dat:
                break
            hasher.update(dat)
        return hasher.hexdigest()

    def get_size(self, pathname):
        """Get the size of a file.
        """
        stat = os.stat(pathname)
        return stat.st_size

    
