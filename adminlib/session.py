import pytz

# pytz is obsolete, but the Archive machine is still on Py3.7 so we're
# stuck with it.

from tinyapp.constants import PLAINTEXT, HTML
from tinyapp.excepts import HTTPError
from tinyapp.util import random_bytes, time_now
from adminlib.util import in_user_time

class User:
    """Represents one user of the admintool.
    We normally have just one of these at a time, representing the user
    who sent a given request. (This is req._user.)

    We also use these in the templates which display lists of users.
    """
    def __init__(self, name, email, roles=None, tzname=None, sessionid=None):
        self.name = name
        self.email = email
        self.sessionid = sessionid
        self.rolestr = roles
        self.roles = set(roles.split(','))

        if 'admin' in self.roles:
            # It's easier to special-case admin here. Add all the roles
            # an admin can do, which is all of them.
            self.roles.update(['incoming', 'index', 'filing', 'rebuild'])
        
        self.tzname = tzname
        self.tz = None
        if tzname:
            try:
                self.tz = pytz.timezone(tzname)
            except:
                pass

    def has_role(self, *roles):
        for role in roles:
            if role in self.roles:
                return True
        return False

class Session:
    """Represents one login session for the admintool.
    
    Sessions are used in the templates which display lists of
    sessions. Note that we don't cache these between requests; they
    are created on the fly for each request.
    """
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
    """Request filter which figures out which user sent the request
    by looking for a session cookie.

    If the session is also due for refreshing, we take care of that (and
    send out a new session cookie).
    
    This sets req._user to a User object if the request was authenticated.
    If not, it leaves req._user as None.

    (Note that this doesn't complain about unauthenticated requests. Use
    require_user() for that.)
    """
    cookiename = req.app.cookieprefix+'sessionid'
    if cookiename not in req.cookies:
        return han(req)
    
    sessionid = req.cookies[cookiename].value
    curs = req.app.getdb().cursor()
    res = curs.execute('SELECT name, starttime, refreshtime FROM sessions WHERE sessionid = ?', (sessionid,))
    tup = res.fetchone()
    if not tup:
        return han(req)
    name, starttime, refreshtime = tup

    now = time_now()
    if now - refreshtime > req.app.max_session_age:
        # Session has expired.
        return han(req)
    if now - refreshtime > req.app.max_session_age / 2:
        # Session is half over. Let's refresh it -- that is, delete it
        # and create a new one.
        # (Only on GET, because I don't want to stick more than one
        # hot dog in the gears at a time.)
        if req.request_method == 'GET':
            curs.execute('DELETE FROM sessions WHERE sessionid = ?', (sessionid,))
            sessionid = random_bytes(20)
            req.set_cookie(req.app.cookieprefix+'sessionid', sessionid, maxage=req.app.max_session_age, httponly=True)
            ipaddr = req.env.get('REMOTE_ADDR', '?')
            curs.execute('INSERT INTO sessions VALUES (?, ?, ?, ?, ?)', (name, sessionid, ipaddr, starttime, now))
            req.loginfo('Refreshed login session: user=%s', name)
    
    res = curs.execute('SELECT email, roles, tzname FROM users WHERE name = ?', (name,))
    tup = res.fetchone()
    if tup:
        email, roles, tzname = tup
        req._user = User(name, email, roles=roles, tzname=tzname, sessionid=sessionid)
        
    return han(req)
        
def require_user(req, han):
    """Request filter which ensures the request is authenticated. If it
    isn't, it throws a 401 error.
    """
    if not req._user:
        raise NotLoggedInError('401 Unauthorized', 'Not logged in')
    return han(req)

def require_role(*roles):
    """Request filter which ensures the request is authenticated as
    a user with a particular role. (Or any one of a list of roles.) If it
    isn't, it throws a 401 error.
    """
    def require(req, han):
        if not req._user:
            raise NotLoggedInError('401 Unauthorized', 'Not logged in')
        got = False
        for role in roles:
            if role in req._user.roles:
                got = True
                break
        if not got:
            raise NotLoggedInError('401 Unauthorized', 'Not authorized for this page')
        return han(req)
    return require

class NotLoggedInError(HTTPError):
    """Not-logged-in error. This is your basic 401, except we display
    a link to the login form.
    """
    def do_error(self, req):
        req.set_content_type(HTML)
        return req.app.render('notloggedin.html', req,
                              status=self.status, msg=self.msg)
        
