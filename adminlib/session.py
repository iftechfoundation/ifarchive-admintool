
from tinyapp.excepts import HTTPError

class User:
    def __init__(self, name, email, roles, sessionid):
        self.name = name
        self.email = email
        self.sessionid = sessionid
        self.roles = set(roles.split(','))
        
def find_user(req, han):
    req._user = None
    
    if 'sessionid' in req.cookies:
        sessionid = req.cookies['sessionid'].value
        curs = req.app.getdb().cursor()
        res = curs.execute('SELECT name FROM sessions WHERE sessionid = ?', (sessionid,))
        tup = res.fetchone()
        if tup:
            name = tup[0]
            res = curs.execute('SELECT email, roles FROM users WHERE name = ?', (name,))
            tup = res.fetchone()
            if tup:
                email, roles = tup
                req._user = User(name, email, roles, sessionid)
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
            raise HTTPError('401 Unauthorized', 'Not authorized for this action')
        return han(req)
    return require
