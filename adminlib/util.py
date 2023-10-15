import time
import pytz
import datetime

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
