import re
import time
import os, os.path
import pytz
import datetime
import hashlib
import urllib.parse
import zipfile


class FileConsistency(Exception):
    """Exception raised when checking file and directory names.
    """
    def __init__(self, msg, dir):
        Exception.__init__(self, '%s: %s' % (msg, dir,))

def canon_archivedir(dirname, archivedir):
    """Verify that a directory path is a valid Archive directory.
    Return its relative path after resolving all symlinks, etc.
    If the path is to the Archive root, returns ''.
    If the path refers to a nonexistent directory, or one outside the
    Archive tree, raises FileConsistency.
    (The archivedir argument must be an absolute path.)
    """
    pathname = os.path.join(archivedir, dirname)
    try:
        # I'd pass strict=True here but that's not available until 3.10. Instead we fake it.
        pathname = os.path.realpath(pathname)
        if not os.path.exists(pathname):
            raise Exception('dir not found')
    except:
        raise FileConsistency('directory not found', dirname)
    
    if not pathname.startswith(archivedir):
        raise FileConsistency('not an Archive directory', dirname)
    if (not os.path.isdir(pathname)) or os.path.islink(pathname):
        raise FileConsistency('not a directory', dirname)
    
    val = pathname[ len(archivedir) : ]
    if val.startswith('/'):
        val = val[ 1 : ]
    return val

def bad_filename(val):
    """Check whether a string is the kind of thing that could cause
    filesystem problems.
    (We're not concerned about shell special characters here.)
    """
    if not val:
        return True
    if '/' in val:
        return True
    if '\x00' in val:
        return True
    if val == '.' or val == '..':
        return True
    return False

pat_numsuffix = re.compile('[.]([0-9])+$')

def find_unused_filename(val, dir):
    """If the filename val is free in dir, return val. Otherwise
    return a variation on val which is free.
    """
    path = os.path.join(dir, val)
    if not os.path.exists(path):
        return val
    
    count = 0
    # Trim off a numbered suffix of val if we see one. (But not if it's
    # the whole of val, e.g. ".123")
    match = pat_numsuffix.search(val)
    if match and match.start() > 0:
        count = int(match.group(1))
        val = val[ : match.start() ]
    while True:
        count += 1
        newval = '%s.%d' % (val, count,)
        path = os.path.join(dir, newval)
        if not os.path.exists(path):
            return newval

def read_md5(pathname):
    """Get an MD5 checksum from a file.
    """
    hasher = hashlib.md5()
    fl = open(pathname, 'rb')
    while True:
        dat = fl.read(8192)
        if not dat:
            break
        hasher.update(dat)
    return hasher.hexdigest()

def read_size(pathname):
    """Get the size of a file.
    """
    stat = os.stat(pathname)
    return stat.st_size

def zip_compress(origpath, newpath):
    """Compress a file. The new pathname must not exist yet.
    """
    outfl = zipfile.ZipFile(newpath, mode='x', compression=zipfile.ZIP_DEFLATED, compresslevel=9)
    outfl.write(origpath, arcname=os.path.basename(origpath))
    outfl.close()

tz_utc = pytz.timezone('UTC')

def in_user_time(user, timestamp):
    """Convert a UNIX timestamp (integer) to a datetime object in the user's
    timezone. If user is not set or has no timezone preference, use UTC.
    """
    dat = datetime.datetime.fromtimestamp(timestamp)
    if user and user.tz:
        dat = dat.astimezone(user.tz)
    else:
        dat = dat.astimezone(tz_utc)
    return dat

def urlencode(val):
    """Percent-encode an URL (or part thereof). This should be compatible
    with the Jinja |urlencode filter, although I haven't completely verified
    that yet.
    """
    return urllib.parse.quote(val)

def clean_newlines(val, prestrip=False):
    """Convert alien newlines to regular newlines.
    Also remove trailing whitespace.
    If prestrip is true, remove leading newlines (but not leading indentation).
    (If the value is completely whitespace, this returns ''.
    Otherwise, the result will end with exactly one newline.)
    """
    val = val.replace('\r\n', '\n')
    val = val.replace('\r', '\n')
    val = val.rstrip()
    if prestrip:
        while val.startswith('\n'):
            val = val[ 1 : ]
    if val:
        val += '\n'
    return val

def sortcanon(val):
    """Lowercase a string for sensible sorting. This is not true
    case-insensitive Unicode sorting, but it covers the common cases.
    We special-case "Index" and ".listing" -- those should always be
    sorted at the top.
    """
    if val == 'Index':
        return '..Index'
    if val == '.listing':
        return '..listing'
    return val.lower()
