import sys
import time
import os
import sqlite3

from tinyapp import TinyApp, ReqHandler
from tinyapp import PLAINTEXT

DB_PATH = '/Users/zarf/src/ifarch/ifarchive-admintool/admin.db'

class AdminApp(TinyApp):
    def __init__(self, hanclasses):
        TinyApp.__init__(self, hanclasses)
        
        self.db = sqlite3.connect(DB_PATH)
        self.db.isolation_level = None   # autocommit

class han_Home(ReqHandler):
    def do_get(self, req):
        yield '<html>Hello world...\n</html>'

class han_DebugDump(ReqHandler):
    def do_get(self, req):
        req.set_content_type(PLAINTEXT)
        yield 'sys.version: %s\n' % (sys.version,)
        yield 'sys.path: %s\n' % (sys.path,)
        yield 'environ:\n'
        for key, val in req.env.items():
            yield '  %s: %s\n' % (key, val,)

class han_DebugUsers(ReqHandler):
    def do_get(self, req):
        req.set_content_type(PLAINTEXT)
        curs = self.app.db.cursor()
        res = curs.execute("SELECT * FROM users")
        while True:
            tup = res.fetchone()
            if not tup:
                break
            yield '%s\n' % (str(tup),)

handlers = [
    ('', han_Home),
    ('/debugusers', han_DebugUsers),
    ('/debugdump', han_DebugDump),
]

application = AdminApp(handlers).application

if __name__ == '__main__':
    uri = ''
    if len(sys.argv) > 1:
        uri = sys.argv[1]
    application.__self__.test_dump(uri)
