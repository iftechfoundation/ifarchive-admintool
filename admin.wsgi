import sys
import time
import os
import hashlib

import sqlite3
from jinja2 import Environment, FileSystemLoader, select_autoescape

from tinyapp.app import TinyApp
from tinyapp.constants import PLAINTEXT
from tinyapp.handler import ReqHandler, before
from tinyapp.excepts import HTTPError, HTTPRedirectPost
from tinyapp.util import random_bytes, time_now
import tinyapp.auth

from adminlib.session import find_user

### config
DB_PATH = '/Users/zarf/src/ifarch/ifarchive-admintool/admin.db'
TEMPLATE_PATH = '/Users/zarf/src/ifarch/ifarchive-admintool/templates'

MAX_SESSION_AGE = 10*60*60*24  # 10 days

class AdminApp(TinyApp):
    def __init__(self, hanclasses):
        TinyApp.__init__(self, hanclasses, wrapall=[
            tinyapp.auth.xsrf_cookie,
            tinyapp.auth.xsrf_check_post
        ])

        self.approot = '/wsgitest' ###config
        
        self.db = sqlite3.connect(DB_PATH)
        self.db.isolation_level = None   # autocommit

        self.jenv = Environment(
            loader = FileSystemLoader(TEMPLATE_PATH),
            autoescape = select_autoescape(),
            keep_trailing_newline = True,
        )
        self.jenv.globals['approot'] = self.approot

    def render(self, template, req, **params):
        tem = self.jenv.get_template(template)
        map = { 'req':req }
        if params:
            map.update(params)
        yield tem.render(**map)


class han_Home(ReqHandler):
    @before(find_user)
    def do_get(self, req):
        if not req._user:
            return self.app.render('login.html', req)

        return self.app.render('front.html', req)

    def do_post(self, req):
        formname = req.get_input_field('name')
        formpw = req.get_input_field('password')

        if not (formname and formpw):
            return self.app.render('login.html', req,
                                   formerror='You must supply name and password.')
        
        curs = self.app.db.cursor()

        if '@' in formname:
            res = curs.execute('SELECT name, pw, pwsalt, roles FROM users WHERE email = ?', (formname,))
        else:
            res = curs.execute('SELECT name, pw, pwsalt, roles FROM users WHERE name = ?', (formname,))
        tup = res.fetchone()
        if not tup:
            return self.app.render('login.html', req,
                                   formerror='The name and password do not match.')
        
        name, pw, pwsalt, roles = tup
        formsalted = pwsalt + b':' + formpw.encode()
        formcrypted = hashlib.sha1(formsalted).hexdigest()
        if formcrypted != pw:
            return self.app.render('login.html', req,
                                   formerror='The name and password do not match.')

        ### set name cookie for future logins? (filled into login.html form)

        sessionid = random_bytes(20)
        req.set_cookie('sessionid', sessionid, maxage=MAX_SESSION_AGE, httponly=True)
        ### also secure=True?
        now = time_now()
        ipaddr = req.env.get('REMOTE_ADDR', '?')
        
        curs = self.app.db.cursor()
        curs.execute('INSERT INTO sessions VALUES (?, ?, ?, ?, ?)', (name, sessionid, ipaddr, now, now))
        
        raise HTTPRedirectPost(self.app.approot)

class han_LogOut(ReqHandler):
    @before(find_user)
    def do_get(self, req):
        if req._user:
            curs = self.app.db.cursor()
            curs.execute('DELETE FROM sessions WHERE sessionid = ?', (req._user.sessionid,))
            # Could clear the sessionid cookie here but I can't seem to make that work
        raise HTTPRedirectPost(self.app.approot)
            

class han_DebugDump(ReqHandler):
    def do_get(self, req):
        req.set_content_type(PLAINTEXT)
        yield 'sys.version: %s\n' % (sys.version,)
        yield 'sys.path: %s\n' % (sys.path,)
        yield 'environ:\n'
        for key, val in req.env.items():
            yield '  %s: %s\n' % (key, val,)
        if 'wsgi.input' in req.env:
            val = req.env['wsgi.input'].read()
            yield 'input: %s' % (val,)

class han_DebugUsers(ReqHandler):
    def do_get(self, req):
        req.set_content_type(PLAINTEXT)
        curs = self.app.db.cursor()
        yield 'Users:\n'
        res = curs.execute('SELECT * FROM users')
        while True:
            tup = res.fetchone()
            if not tup:
                break
            yield '- %s\n' % (str(tup),)
        yield 'Sessions:\n'
        res = curs.execute('SELECT * FROM sessions')
        while True:
            tup = res.fetchone()
            if not tup:
                break
            yield '- %s\n' % (str(tup),)

handlers = [
    ('', han_Home),
    ('/logout', han_LogOut),
    ('/debugusers', han_DebugUsers),
    ('/debugdump', han_DebugDump),
]

appinstance = AdminApp(handlers)
application = appinstance.application



if __name__ == '__main__':
    import adminlib.cli
    adminlib.cli.run(appinstance)
