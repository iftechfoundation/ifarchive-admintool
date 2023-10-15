import re
import time
import pytz
import datetime

import jinja2.ext

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
        
