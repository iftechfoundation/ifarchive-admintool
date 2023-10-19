import pytz

# pytz is obsolete, but the Archive machine is still on Py3.7 so we're
# stuck with it.

from tinyapp.excepts import HTTPError
from adminlib.util import in_user_time

class User:
    def __init__(self, name, email, roles=None, tzname=None, sessionid=None):
        self.name = name
        self.email = email
        self.sessionid = sessionid
        self.roles = set(roles.split(','))
        
        self.tzname = tzname
        self.tz = None
        if tzname:
            try:
                self.tz = pytz.timezone(tzname)
            except:
                pass

class Session:
    def __init__(self, tup, user=None, maxage=None):
        name, ipaddr, starttime, refreshtime = tup
        self.name = name
        self.ipaddr = ipaddr
        self.starttime = starttime
        self.refreshtime = refreshtime

        mtime = in_user_time(user, starttime)
        self.fstarttime = mtime.strftime('%b %d, %H:%M %Z')
        mtime = in_user_time(user, refreshtime)
        self.frefreshtime = mtime.strftime('%b %d, %H:%M %Z')

        self.expiretime = None
        self.fexpiretime = None
        if maxage:
            self.expiretime = self.refreshtime + maxage
            mtime = in_user_time(user, self.expiretime)
            self.fexpiretime = mtime.strftime('%b %d, %H:%M %Z')


def find_user(req, han):
    if 'sessionid' in req.cookies:
        sessionid = req.cookies['sessionid'].value
        curs = req.app.getdb().cursor()
        ### also restrict by refreshtime?
        res = curs.execute('SELECT name FROM sessions WHERE sessionid = ?', (sessionid,))
        tup = res.fetchone()
        if tup:
            name = tup[0]
            res = curs.execute('SELECT email, roles, tzname FROM users WHERE name = ?', (name,))
            tup = res.fetchone()
            if tup:
                email, roles, tzname = tup
                req._user = User(name, email, roles=roles, tzname=tzname, sessionid=sessionid)
    return han(req)
        
def require_user(req, han):
    if not req._user:
        raise HTTPError('401 Unauthorized', 'Not logged in')
    return han(req)

def require_role(*roles):
    def require(req, han):
        if not req._user:
            raise HTTPError('401 Unauthorized', 'Not logged in')
        got = False
        for role in roles:
            if role in req._user.roles:
                got = True
                break
        if not got:
            raise HTTPError('401 Unauthorized', 'Not authorized for this page')
        return han(req)
    return require
