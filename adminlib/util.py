import re
import time
import os.path
import pytz
import datetime

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
        
