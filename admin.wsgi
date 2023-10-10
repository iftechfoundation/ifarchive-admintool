import sys
import time
import os

import sqlite3
from jinja2 import Environment, FileSystemLoader, select_autoescape

from tinyapp import TinyApp, ReqHandler
from tinyapp import PLAINTEXT

DB_PATH = '/Users/zarf/src/ifarch/ifarchive-admintool/admin.db'
TEMPLATE_PATH = '/Users/zarf/src/ifarch/ifarchive-admintool/lib'

class AdminApp(TinyApp):
    def __init__(self, hanclasses):
        TinyApp.__init__(self, hanclasses)
        
        self.db = sqlite3.connect(DB_PATH)
        self.db.isolation_level = None   # autocommit

        self.jenv = Environment(
            loader = FileSystemLoader(TEMPLATE_PATH),
            autoescape = select_autoescape(),
            keep_trailing_newline = True,
        )

def random_bytes(count):
    byt = os.urandom(count)
    return bytes.hex(byt)
        
def xsrf_cookie(han):
    def wrapper(self, req):
        if '_xsrf' in req.cookies:
            req._xsrf = req.cookies['_xsrf'].value
        else:
            req._xsrf = random_bytes(16)
            ### also secure=True?
            req.set_cookie('_xsrf', req._xsrf, httponly=True)
            
        return han(self, req)
    
    return wrapper
        
class han_Home(ReqHandler):
    @xsrf_cookie
    def do_get(self, req):
        template = self.app.jenv.get_template('front.html')
        yield template.render()

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
