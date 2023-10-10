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
from tinyapp.util import random_bytes
import tinyapp.auth

### config
DB_PATH = '/Users/zarf/src/ifarch/ifarchive-admintool/admin.db'
TEMPLATE_PATH = '/Users/zarf/src/ifarch/ifarchive-admintool/lib'

class AdminApp(TinyApp):
    def __init__(self, hanclasses):
        TinyApp.__init__(self, hanclasses, wrapall=[ tinyapp.auth.xsrf_cookie ])

        self.approot = '/wsgitest' ###config
        
        self.db = sqlite3.connect(DB_PATH)
        self.db.isolation_level = None   # autocommit

        self.jenv = Environment(
            loader = FileSystemLoader(TEMPLATE_PATH),
            autoescape = select_autoescape(),
            keep_trailing_newline = True,
        )
        self.jenv.globals['approot'] = self.approot

class han_Home(ReqHandler):
    def do_get(self, req):
        template = self.app.jenv.get_template('login.html')
        yield template.render(
            req=req)

    def do_post(self, req):
        formname = req.get_input_field('name')
        formpw = req.get_input_field('password')
        
        curs = self.app.db.cursor()

        if '@' in formname:
            res = curs.execute("SELECT name, pw, pwsalt, roles FROM users WHERE email = ?", (formname,))
        else:
            res = curs.execute("SELECT name, pw, pwsalt, roles FROM users WHERE name = ?", (formname,))
        tup = res.fetchone()
        if not tup:
            template = self.app.jenv.get_template('login.html')
            yield template.render(
                formerror='The name and password do not match.',
	            req=req)
            return
        name, pw, pwsalt, roles = tup

        formsalted = pwsalt + b':' + formpw.encode()
        formcrypted = hashlib.sha1(formsalted).hexdigest()
        if formcrypted != pw:
            template = self.app.jenv.get_template('login.html')
            yield template.render(
                formerror='The name and password do not match.###pw',
	            req=req)
            return

        ### set name cookie for future logins? (filled in in login.html)

        ### create session
        raise HTTPRedirectPost('/') ###
        
class han_DebugDump(ReqHandler):
    def do_get(self, req):
        req.set_content_type(PLAINTEXT)
        yield 'sys.version: %s\n' % (sys.version,)
        yield 'sys.path: %s\n' % (sys.path,)
        yield 'environ:\n'
        for key, val in req.env.items():
            yield '  %s: %s\n' % (key, val,)
        val = req.env['wsgi.input'].read()
        yield 'input: %s' % (val,)

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

appinstance = AdminApp(handlers)
application = appinstance.application


def db_create():
    curs = appinstance.db.cursor()
    res = curs.execute('SELECT name FROM sqlite_master')
    tables = [ tup[0] for tup in res.fetchall() ]
    if 'users' in tables:
        print('"users" table exists')
    else:
        print('creating "users" table...')
        curs.execute('CREATE TABLE users(name unique, email unique, pw, pwsalt, roles)')
    if 'sessions' in tables:
        print('"sessions" table exists')
    else:
        print('creating "sessions" table...')
        curs.execute('CREATE TABLE sessions(name, cookie unique, start)')


def db_add_user(args):
    if len(args) != 4:
        print('usage: adduser name email pw role1,role2,role3')
        return
    name, email, pw, roles = args
    pwsalt = random_bytes(8).encode()
    salted = pwsalt + b':' + pw.encode()
    crypted = hashlib.sha1(salted).hexdigest()
    print('adding users "%s"...' % (name,))
    curs = appinstance.db.cursor()
    curs.execute('INSERT INTO users VALUES (?, ?, ?, ?, ?)', (name, email, crypted, pwsalt, roles))
    
if __name__ == '__main__':
    import optparse

    popt = optparse.OptionParser(usage='admin.wsgi createdb | adduser | test')
    (opts, args) = popt.parse_args()

    if not args:
        print('command-line use:')
        print('  admin.wsgi createdb: create database tables')
        print('  admin.wsgi adduser name email pw roles: add a user')
        print('  admin.wsgi test [ URI ]: print page to stdout')
        sys.exit(-1)

    cmd = args.pop(0)
    
    if cmd == 'test':
        uri = ''
        if args:
            uri = args[0]
        appinstance.test_dump(uri)
    elif cmd == 'createdb':
        db_create()
    elif cmd == 'adduser':
        db_add_user(args)
    else:
        print('command not recognized: %s' % (cmd,))
        print('Usage: %s' % (popt.usage,))
