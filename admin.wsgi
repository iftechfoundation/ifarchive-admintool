import sys
import time
import os, os.path
import hashlib
import configparser
import threading
import logging, logging.handlers

import sqlite3
from jinja2 import Environment, FileSystemLoader, select_autoescape

configpath = '/Users/zarf/src/ifarch/ifarchive-admintool/test.config'
#configpath = '/var/ifarchive/lib/ifarch.config'
config = configparser.ConfigParser()
config.read(configpath)

DB_PATH = config['DEFAULT']['DBFile']
INCOMING_DIR = config['DEFAULT']['IncomingDir']
TRASH_DIR = config['DEFAULT']['TrashDir']
ARCHIVE_DIR = config['DEFAULT']['ArchiveDir']

TEMPLATE_PATH = config['AdminTool']['TemplateDir']
MAX_SESSION_AGE = config['AdminTool'].getint('MaxSessionAge')
APP_ROOT = config['AdminTool']['AppRoot']
APP_CSS_URI = config['AdminTool']['AppCSSURI']

# Set up PyLibPath before we start importing tinyapp modules
if 'PyLibPath' in config['AdminTool']:
    val = config['AdminTool']['PyLibPath']
    if val not in sys.path:
        sys.path.append(val)

# Set up the logging configuration
loghandler = logging.handlers.WatchedFileHandler(config['AdminTool']['LogFile'])
logging.basicConfig(
    format = '[%(levelname).1s %(asctime)s] %(message)s',
    datefmt = '%b-%d %H:%M:%S',
    level = logging.INFO,
    handlers = [ loghandler ],
)

from tinyapp.app import TinyApp, TinyRequest
from tinyapp.constants import PLAINTEXT, BINARY
from tinyapp.handler import ReqHandler, before, beforeall
from tinyapp.excepts import HTTPError, HTTPRedirectPost, HTTPRawResponse
from tinyapp.util import random_bytes, time_now
import tinyapp.auth

from adminlib.session import find_user, User
from adminlib.session import require_user, require_role
from adminlib.util import bad_filename, in_user_time
from adminlib.util import DelimNumber, find_unused_filename

class AdminApp(TinyApp):
    def __init__(self, hanclasses):
        TinyApp.__init__(self, hanclasses, wrapall=[
            tinyapp.auth.xsrf_cookie,
            tinyapp.auth.xsrf_check_post,
            find_user,
        ])

        self.approot = APP_ROOT
        self.incoming_dir = INCOMING_DIR
        self.trash_dir = TRASH_DIR
        self.archive_dir = ARCHIVE_DIR
        self.unprocessed_dir = os.path.join(ARCHIVE_DIR, 'unprocessed')

        # Thread-local storage for various things which are not thread-safe.
        self.threadcache = threading.local()

    def getdb(self):
        """Get or create a sqlite3 db connection object. These are
        cached per-thread.
        (The sqlite3 module is thread-safe, but the db connection objects
        you get from it might not be shareable between threads. Depends on
        the version of SQLite installed, but we take no chances.)
        """
        db = getattr(self.threadcache, 'db', None)
        if db is None:
            db = sqlite3.connect(DB_PATH)
            db.isolation_level = None   # autocommit
            self.threadcache.db = db
        return db

    def getjenv(self):
        """Get or create a jinja template environment. These are
        cached per-thread.
        """
        jenv = getattr(self.threadcache, 'jenv', None)
        if jenv is None:
            jenv = Environment(
                loader = FileSystemLoader(TEMPLATE_PATH),
                extensions = [
                    DelimNumber,
                ],
                autoescape = select_autoescape(),
                keep_trailing_newline = True,
            )
            jenv.globals['approot'] = self.approot
            jenv.globals['appcssuri'] = APP_CSS_URI
            self.threadcache.jenv = jenv
        return jenv

    def create_request(self, environ):
        """Create a request object.
        Returns our subclass of TinyRequest.
        """
        return AdminRequest(self, environ)

    def render(self, template, req, **params):
        """Render a template for the current request. This adds in some
        per-request template parameters.
        """
        tem = self.getjenv().get_template(template)
        # The requri is de-escaped, which is what we want -- it will be
        # used for <form action="requri">.
        map = {
            'req': req,
            'requri': req.app.approot+req.env['PATH_INFO'],
            'user': req._user,
        }
        if params:
            map.update(params)
        yield tem.render(**map)


class AdminRequest(TinyRequest):
    def __init__(self, app, env):
        TinyRequest.__init__(self, app, env)

        # Initialize our app-specific fields.
        self._user = None

    def lognote(self):
        if not self._user:
            return 'user=(none)'
        else:
            return 'user=%s' % (self._user.name,)

class AdminHandler(ReqHandler):
    renderparams = None
    
    def render(self, template, req, **params):
        """Render a template for the current request. This adds in some
        per-handler template parameters.
        """
        if not self.renderparams:
            map = params
        else:
            map = dict(self.renderparams)
            map.update(params)
        return self.app.render(template, req, **map)

    
# URL handlers...

class han_Home(AdminHandler):
    renderparams = { 'navtab':'top' }
    
    def do_get(self, req):
        if not req._user:
            return self.render('login.html', req)

        incount = len([ ent for ent in os.scandir(self.app.incoming_dir) if ent.is_file() ])

        return self.render('front.html', req, incount=incount)

    def do_post(self, req):
        formname = req.get_input_field('name')
        formpw = req.get_input_field('password')

        if not (formname and formpw):
            return self.render('login.html', req,
                                   formerror='You must supply name and password.')
        
        curs = self.app.getdb().cursor()

        if '@' in formname:
            res = curs.execute('SELECT name, pw, pwsalt, roles FROM users WHERE email = ?', (formname,))
        else:
            res = curs.execute('SELECT name, pw, pwsalt, roles FROM users WHERE name = ?', (formname,))
        tup = res.fetchone()
        if not tup:
            return self.render('login.html', req,
                                   formerror='The name and password do not match.')
        
        name, pw, pwsalt, roles = tup
        formsalted = pwsalt + b':' + formpw.encode()
        formcrypted = hashlib.sha1(formsalted).hexdigest()
        if formcrypted != pw:
            return self.render('login.html', req,
                                   formerror='The name and password do not match.')

        ### set name cookie for future logins? (filled into login.html form)

        sessionid = random_bytes(20)
        req.set_cookie('sessionid', sessionid, maxage=MAX_SESSION_AGE, httponly=True)
        ### also secure=True?
        now = time_now()
        ipaddr = req.env.get('REMOTE_ADDR', '?')
        
        curs = self.app.getdb().cursor()
        curs.execute('INSERT INTO sessions VALUES (?, ?, ?, ?, ?)', (name, sessionid, ipaddr, now, now))
        
        req.loginfo('Logged in: user=%s, roles=%s', name, roles)
        raise HTTPRedirectPost(self.app.approot)

class han_LogOut(AdminHandler):
    def do_get(self, req):
        if req._user:
            curs = self.app.getdb().cursor()
            curs.execute('DELETE FROM sessions WHERE sessionid = ?', (req._user.sessionid,))
            # Could clear the sessionid cookie here but I can't seem to make that work
        raise HTTPRedirectPost(self.app.approot)

@beforeall(require_user)
class han_UserProfile(AdminHandler):
    def do_get(self, req):
        return self.render('user.html', req)

@beforeall(require_user)
class han_ChangePW(AdminHandler):
    def do_get(self, req):
        return self.render('changepw.html', req)
    
    def do_post(self, req):
        oldpw = req.get_input_field('oldpassword')
        newpw = req.get_input_field('newpassword')
        duppw = req.get_input_field('duppassword')
        if not newpw:
            return self.render('changepw.html', req,
                                   formerror='You must supply a new password.')

        curs = self.app.getdb().cursor()
        res = curs.execute('SELECT pw, pwsalt FROM users WHERE name = ?', (req._user.name,))
        tup = res.fetchone()
        if not tup:
            return self.render('changepw.html', req,
                                   formerror='Cannot locate user record.')
        pw, pwsalt = tup
        formsalted = pwsalt + b':' + oldpw.encode()
        formcrypted = hashlib.sha1(formsalted).hexdigest()
        if formcrypted != pw:
            return self.render('changepw.html', req,
                                   formerror='Old password does not match.')
        if newpw != duppw:
            return self.render('changepw.html', req,
                                   formerror='New password does not match.')

        pwsalt = random_bytes(8).encode()
        salted = pwsalt + b':' + newpw.encode()
        crypted = hashlib.sha1(salted).hexdigest()
        curs.execute('UPDATE users SET pw = ?, pwsalt = ? WHERE name = ?', (crypted, pwsalt, req._user.name))
        
        req.loginfo('Changed password')
        return self.render('changepwdone.html', req)
            

@beforeall(require_user)
class han_ChangeTZ(AdminHandler):
    def do_get(self, req):
        return self.render('changetz.html', req)
    
    def do_post(self, req):
        tzname = req.get_input_field('tz_field')
        curs = self.app.getdb().cursor()
        curs.execute('UPDATE users SET tzname = ? WHERE name = ?', (tzname, req._user.name))
        req.loginfo('Changed timezone to %s', tzname)
        raise HTTPRedirectPost(self.app.approot+'/user')


@beforeall(require_role('admin'))
class han_AdminAdmin(AdminHandler):
    renderparams = { 'navtab':'admin' }

    def do_get(self, req):
        return self.render('admin.html', req)


@beforeall(require_role('admin'))
class han_AllUsers(AdminHandler):
    renderparams = { 'navtab':'admin' }

    def do_get(self, req):
        curs = self.app.getdb().cursor()
        res = curs.execute('SELECT name, email, roles FROM users')
        userlist = [ User(name, email, roles=roles) for name, email, roles in res.fetchall() ]
        #res = curs.execute('SELECT name, ipaddr, starttime FROM sessions')
        #sessionlist = res.fetchall()
        return self.render('allusers.html', req,
                               users=userlist)


@beforeall(require_role('incoming', 'admin'))
class han_Incoming(AdminHandler):
    renderparams = { 'navtab':'incoming' }

    def get_filelist(self, req):
        filelist = []
        for ent in os.scandir(self.app.incoming_dir):
            if ent.is_file():
                stat = ent.stat()
                mtime = in_user_time(req._user, stat.st_mtime)
                file = {
                    'name': ent.name,
                    'date': stat.st_mtime,
                    'fdate': mtime.strftime('%b %d, %H:%M %Z'),
                    'size': stat.st_size,
                }
                filelist.append(file)
        filelist.sort(key=lambda file:file['date'])
        return filelist

    def get_trashcount(self, req):
        count = len([ ent for ent in os.scandir(self.app.trash_dir) if ent.is_file() ])
        return count
    
    def do_get(self, req):
        filelist = self.get_filelist(req)
        trashcount = self.get_trashcount(req)
        return self.render('incoming.html', req,
                               files=filelist, trashcount=trashcount)
    
    def do_post(self, req):
        filelist = self.get_filelist(req)
        trashcount = self.get_trashcount(req)
        filename = req.get_input_field('filename')
        subls = [ ent for ent in filelist if ent['name'] == filename ]
        if bad_filename(filename) or not subls:
            return self.render('incoming.html', req,
                               files=filelist, trashcount=trashcount,
                               formerror='Invalid filename: "%s"' % (filename,))
        ent = subls[0]
        if req.get_input_field('cancel'):
            raise HTTPRedirectPost(self.app.approot+'/incoming')
        
        if req.get_input_field('op'):
            op = req.get_input_field('op')
        elif req.get_input_field('delete'):
            op = 'delete'
        elif req.get_input_field('move'):
            op = 'move'
        elif req.get_input_field('rename'):
            op = 'rename'
        else:
            return self.render('incoming.html', req,
                               files=filelist, trashcount=trashcount,
                               formerror='Invalid operation')

        if not req.get_input_field('confirm'):
            return self.render('incoming.html', req,
                               files=filelist, trashcount=trashcount,
                               op=op, opfile=filename)

        if op == 'delete':
            newname = find_unused_filename(filename, self.app.trash_dir)
            origpath = os.path.join(self.app.incoming_dir, filename)
            newpath = os.path.join(self.app.trash_dir, newname)
            os.rename(origpath, newpath)
            req.loginfo('Deleted "%s" from /incoming', filename)
            # Gotta reload filelist and trashcount, for they have changed
            filelist = self.get_filelist(req)
            trashcount = self.get_trashcount(req)
            return self.render('incoming.html', req,
                               files=filelist, trashcount=trashcount,
                               diddelete=filename, didnewname=newname)
        
        elif op == 'move':
            newname = find_unused_filename(filename, self.app.unprocessed_dir)
            origpath = os.path.join(self.app.incoming_dir, filename)
            newpath = os.path.join(self.app.unprocessed_dir, newname)
            os.rename(origpath, newpath)
            req.loginfo('Moved "%s" from /incoming to /unprocessed', filename)
            # Gotta reload filelist, for it as changed
            filelist = self.get_filelist(req)
            return self.render('incoming.html', req,
                               files=filelist, trashcount=trashcount,
                               didmove=filename, didnewname=newname)
        
        elif op == 'rename':
            newname = req.get_input_field('newname')
            if newname is not None:
                newname = newname.strip()
            if not newname:
                return self.render('incoming.html', req,
                                   files=filelist, trashcount=trashcount,
                                   op=op, opfile=filename,
                                   formerror='You must supply a filename.')
            if bad_filename(newname):
                return self.render('incoming.html', req,
                                   files=filelist, trashcount=trashcount,
                                   op=op, opfile=filename,
                                   formerror='Invalid filename: "%s"' % (newname,))
            origpath = os.path.join(self.app.incoming_dir, filename)
            newpath = os.path.join(self.app.incoming_dir, newname)
            if os.path.exists(newpath):
                return self.render('incoming.html', req,
                                   files=filelist, trashcount=trashcount,
                                   op=op, opfile=filename,
                                   formerror='Filename already in use: "%s"' % (newname,))
            os.rename(origpath, newpath)
            req.loginfo('Renamed "%s" to "%s" in /incoming', filename, newname)
            # Gotta reload filelist, for it has changed
            filelist = self.get_filelist(req)
            return self.render('incoming.html', req,
                               files=filelist, trashcount=trashcount,
                               didrename=filename, didnewname=newname)
        else:
            return self.render('incoming.html', req,
                               files=filelist, trashcount=trashcount,
                               formerror='Operation not implemented: %s' % (op,))


@beforeall(require_role('incoming', 'admin'))
class han_Trash(AdminHandler):
    renderparams = { 'navtab':'trash' }

    def get_filelist(self, req):
        filelist = []
        for ent in os.scandir(self.app.trash_dir):
            if ent.is_file():
                stat = ent.stat()
                mtime = in_user_time(req._user, stat.st_mtime)
                file = {
                    'name': ent.name,
                    'date': stat.st_mtime,
                    'fdate': mtime.strftime('%b %d, %H:%M %Z'),
                    'size': stat.st_size,
                }
                filelist.append(file)
        filelist.sort(key=lambda file:file['date'])
        return filelist

    def do_get(self, req):
        filelist = self.get_filelist(req)
        return self.render('trash.html', req,
                               files=filelist)
    
    def do_post(self, req):
        filelist = self.get_filelist(req)
        filename = req.get_input_field('filename')
        subls = [ ent for ent in filelist if ent['name'] == filename ]
        if bad_filename(filename) or not subls:
            return self.render('trash.html', req,
                               files=filelist,
                               formerror='Invalid filename: "%s"' % (filename,))
        ent = subls[0]
        if req.get_input_field('cancel'):
            raise HTTPRedirectPost(self.app.approot+'/trash')
        
        if req.get_input_field('op'):
            op = req.get_input_field('op')
        elif req.get_input_field('restore'):
            op = 'restore'
        else:
            return self.render('trash.html', req,
                               files=filelist,
                               formerror='Invalid operation')

        if not req.get_input_field('confirm'):
            return self.render('trash.html', req,
                               files=filelist,
                               op=op, opfile=filename)

        if op == 'restore':
            newname = find_unused_filename(filename, self.app.incoming_dir)
            origpath = os.path.join(self.app.trash_dir, filename)
            newpath = os.path.join(self.app.incoming_dir, newname)
            os.rename(origpath, newpath)
            req.loginfo('Restored "%s" from /trash to /incoming', filename)
            # Gotta reload filelist, for it has changed
            filelist = self.get_filelist(req)
            return self.render('trash.html', req,
                               files=filelist,
                               didrestore=filename, didnewname=newname)
        else:
            return self.render('trash.html', req,
                               files=filelist,
                               formerror='Operation not implemented: %s' % (op,))



def RawDownload(dirname, filename):
    if bad_filename(filename):
        msg = 'Not found: %s' % (filename,)
        raise HTTPError('404 Not Found', msg)
    pathname = os.path.join(dirname, filename)
    try:
        stat = os.stat(pathname)
        filesize = stat.st_size
    except Exception as ex:
        msg = 'Unable to stat: %s %s' % (pathname, ex,)
        raise HTTPError('400 Not Readable', msg)
    
    fl = None
    try:
        fl = open(pathname, 'rb')
    except Exception as ex:
        msg = 'Unable to read: %s %s' % (pathname, ex,)
        raise HTTPError('400 Not Readable', msg)
    
    response_headers = [
        ('Content-Type', BINARY),
        ('Content-Length', str(filesize)),
        ('Content-Disposition', 'attachment; filename="%s"' % (filename.replace('"', '_'),))
    ]
    def resp():
        while True:
            val = fl.read(8192)
            if not val:
                break
            yield val
        fl.close()
        return
    raise HTTPRawResponse('200 OK', response_headers, resp())

@beforeall(require_role('incoming', 'admin'))
class han_DLIncoming(AdminHandler):
    def do_get(self, req):
        filename = req.matchgroups[0]
        RawDownload(self.app.incoming_dir, filename)

@beforeall(require_role('incoming', 'admin'))
class han_DLTrash(AdminHandler):
    def do_get(self, req):
        filename = req.matchgroups[0]
        RawDownload(self.app.trash_dir, filename)

class han_DebugDump(AdminHandler):
    def do_get(self, req):
        req.set_content_type(PLAINTEXT)
        yield 'sys.version: %s\n' % (sys.version,)
        yield 'sys.path: %s\n' % (sys.path,)
        if req.matchgroups:
            yield 'matchgroups: %s\n' % (req.matchgroups,)
        yield 'getpid=%s\n' % (os.getpid(),)
        yield 'getlogin=%s, getuid=%s, geteuid=%s, getgid=%s, getegid=%s\n' % (os.getlogin(), os.getuid(), os.geteuid(), os.getgid(), os.getegid(),)
        yield 'environ:\n'
        for key, val in req.env.items():
            yield '  %s: %s\n' % (key, val,)
        if 'wsgi.input' in req.env:
            val = req.env['wsgi.input'].read()
            yield 'input: %s' % (val,)

handlers = [
    ('', han_Home),
    ('/logout', han_LogOut),
    ('/user', han_UserProfile),
    ('/user/changepw', han_ChangePW),
    ('/user/changetz', han_ChangeTZ),
    ('/admin', han_AdminAdmin),
    ('/admin/allusers', han_AllUsers),
    ('/incoming', han_Incoming),
    ('/incoming/download/(.+)', han_DLIncoming),
    ('/trash', han_Trash),
    ('/trash/download/(.+)', han_DLTrash),
    ('/debugdump', han_DebugDump),
    ('/debugdump/(.+)', han_DebugDump),
]

appinstance = AdminApp(handlers)
application = appinstance.application



if __name__ == '__main__':
    import adminlib.cli
    adminlib.cli.run(appinstance)
