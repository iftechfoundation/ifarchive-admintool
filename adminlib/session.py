
class User:
    def __init__(self, name, sessionid, roles):
        self.name = name
        self.sessionid = sessionid
        self.roles = set(roles.split(','))
        
def find_user(req, han):
    req._user = None
    
    if 'sessionid' in req.cookies:
        sessionid = req.cookies['sessionid'].value
        curs = req.app.db.cursor()
        res = curs.execute('SELECT name FROM sessions WHERE sessionid = ?', (sessionid,))
        tup = res.fetchone()
        if tup:
            name = tup[0]
            res = curs.execute('SELECT roles FROM users WHERE name = ?', (name,))
            tup = res.fetchone()
            if tup:
                roles = tup[0]
                req._user = User(name, sessionid, roles)
    return han(req)
        
