import re
import time
import os, os.path
import pytz
import datetime
import hashlib
import zipfile

import jinja2.ext

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


class DelimNumber(jinja2.ext.Extension):
    """Jinja extension: Display a number with place separators.
    E.g "12,345,678". If the value is not an integer or str(int),
    return it unchanged.
    """
    pat_alldigits = re.compile('^[0-9]+$')

    def __init__(self, env):
        env.filters['delimnumber'] = self.delim_number

    @staticmethod
    def delim_number(val):
        val = str(val)
        if not DelimNumber.pat_alldigits.match(val):
            return val
    
        ls = []
        lenv = len(val)
        pos = lenv % 3
        if pos:
            ls.append(val[ 0 : pos ])
        while pos < lenv:
            ls.append(val[ pos : pos+3 ])
            pos += 3
        return ','.join(ls)
        
