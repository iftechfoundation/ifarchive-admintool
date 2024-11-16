#!/usr/bin/env python3

"""
AdminTool: Web app for IF Archive administration.

See tinyapp/app.py for how the underlying web app framework works.

This file (admin.wsgi) is installed as /var/ifarchive/wsgi-bin/admin.wsgi.
It can also be run to perform some command-line operations:

  python3 /var/ifarchive/wsgi-bin/admin.wsgi
"""

import sys
import time
import os, os.path
import hashlib
import urllib.request, urllib.error
import configparser
import shutil
import subprocess
import logging, logging.handlers
import threading

from tinyapp.constants import PLAINTEXT, BINARY
from tinyapp.handler import before, beforeall
from tinyapp.excepts import HTTPError, HTTPRedirectPost, HTTPRawResponse
from tinyapp.util import random_bytes, time_now

from adminlib.admapp import AdminApp, AdminHandler
from adminlib.session import User, Session
from adminlib.session import require_user, require_role
from adminlib.util import bad_filename, in_user_time, clean_newlines
from adminlib.util import zip_compress
from adminlib.util import find_unused_filename
from adminlib.util import urlencode
from adminlib.util import canon_archivedir, FileConsistency
from adminlib.util import sortcanon
from adminlib.util import log_files_tail
from adminlib.info import FileEntry, DirEntry, SymlinkEntry, IndexOnlyEntry, UploadEntry
from adminlib.info import get_dir_entries, dir_is_empty
from adminlib.index import IndexDir, update_file_entries


    
# URL handlers...

class han_Home(AdminHandler):
    renderparams = { 'navtab':'top' }

    def add_renderparams(self, req, map):
        cookiename = req.app.cookieprefix+'username'
        if cookiename in req.cookies:
            map['username'] = req.cookies[cookiename].value
        return map
    
    def do_get(self, req):
        if not req._user:
            return self.render('login.html', req)

        incount = len([ ent for ent in os.scandir(self.app.incoming_dir) if ent.is_file() ])
        
        # Sorry about the special case.
        unproccount = len([ ent for ent in os.scandir(self.app.unprocessed_dir) if ent.is_file() and ent.name != '.listing' ])

        locktime = self.app.get_locktime()
        buildtime, builddesc = self.app.get_buildinfo(user=req._user)

        diskuse = shutil.disk_usage(self.app.archive_dir)

        return self.render('front.html', req,
                           incount=incount, unproccount=unproccount,
                           locktime=locktime,
                           buildtime=buildtime, builddesc=builddesc,
                           diskuse=diskuse)

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

        sessionid = random_bytes(20)
        req.set_cookie(self.app.cookieprefix+'sessionid', sessionid, maxage=self.app.max_session_age, httponly=True)
        req.set_cookie(self.app.cookieprefix+'username', name, httponly=True)
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
        return self.render('allusers.html', req,
                               users=userlist)


@beforeall(require_role('admin'))
class han_AllSessions(AdminHandler):
    renderparams = { 'navtab':'admin' }

    def do_get(self, req):
        curs = self.app.getdb().cursor()
        res = curs.execute('SELECT name, ipaddr, starttime, refreshtime FROM sessions')
        sessionlist = [ Session(tup, user=req._user, maxage=self.app.max_session_age) for tup in res.fetchall() ]
        return self.render('allsessions.html', req,
                               sessions=sessionlist)


@beforeall(require_role('admin'))
class han_HashCache(AdminHandler):
    renderparams = { 'navtab':'admin' }

    def do_get(self, req):
        cachels = self.app.hasher.dump()
        pid = os.getpid()
        return self.render('hashcache.html', req,
                           cachels=cachels, pid=pid)

        
class base_DirectoryPage(AdminHandler):
    """Base class for all handlers that display a file list.
    This will have subclasses for each directory that has special
    handling. (Incoming, Trash, etc.)
    
    This is rather long and messy because it also handles all the
    buttons that can appear under a file name: Move, Rename, Delete,
    and so on.
    """

    # Should we load UploadEntry info for files in this directory?
    # (Subclasses may override this to be true.)
    autoload_uploadinfo = False
    
    def get_dirpath(self, req):
        """Return the (full) filesystem path of the directory that this
        subclass will operate on. (E.g. "/var/ifarchive/incoming" or
        "/var/ifarchive/htdocs/if-archive/unprocessed".)
        Subclasses must customize this.
        """
        raise NotImplementedError('%s: get_dirpath not implemented' % (self.__class__.__name__,))

    def get_dirname(self, req):
        """Return the printable name of the directory that this
        subclass will operate on. (E.g. "incoming" or "unprocessed".)
        Subclasses must customize this.
        """
        raise NotImplementedError('%s: get_dirname not implemented' % (self.__class__.__name__,))

    def check_fileops(self, req):
        """Add a req._fileops field, containing file operations valid for
        the current user in this directory.
        Subclasses should customize get_fileops(), not this method.
        """
        req._fileops = set()
        if req._user:
            ops = self.get_fileops(req)
            if ops:
                req._fileops.update(ops)

    def get_fileops(self, req):
        """Return the operations which are available for files in this
        directory. This should be limited to what the req._user's roles
        allow.
        (You can assume that req._user is set when this is called.)
        Subclasses should customize this to permit appropriate operations.
        """
        return None

    def get_file(self, filename, req):
        """Get one FileEntry from our directory, or None if the file
        does not exist.
        """
        if bad_filename(filename):
            return None
        pathname = os.path.join(self.get_dirpath(req), filename)
        if not os.path.exists(pathname):
            return None
        if not os.path.isfile(pathname):
            return None
        stat = os.stat(pathname)
        return FileEntry(filename, stat, user=req._user)
        
    def get_dirent(self, filename, req):
        """Same as above, but for subdirectories.
        """
        if bad_filename(filename):
            return None
        pathname = os.path.join(self.get_dirpath(req), filename)
        if not os.path.exists(pathname):
            return None
        if not os.path.isdir(pathname):
            return None
        stat = os.stat(pathname)
        return DirEntry(filename, stat, user=req._user)
        
    def get_symlink(self, filename, req):
        """Same as above, but for symlinks.
        """
        if bad_filename(filename):
            return None
        pathname = os.path.join(self.get_dirpath(req), filename)
        if not os.path.islink(pathname):
            return None
        target = os.readlink(pathname)
        path = os.path.realpath(pathname)
        if path.startswith(self.app.archive_dir+'/') and os.path.exists(path):
            relpath = path[ len(self.app.archive_dir)+1 : ]
            if os.path.isfile(path):
                stat = os.stat(path)
                return SymlinkEntry(filename, target, stat, realpath=relpath, isdir=False, user=req._user)
            elif os.path.isdir(path):
                stat = os.stat(path)
                return SymlinkEntry(filename, target, stat, realpath=relpath, isdir=True, user=req._user)
            else:
                return None
        else:
            # Gotta use the link's own stat
            stat = os.lstat(pathname)
            return SymlinkEntry(filename, target, stat, isdir=False, broken=True, user=req._user)
        
    def get_filelist(self, req, dirs=False, shortdate=False, sort=None):
        """Get a list of FileEntries from our directory.
        See get_dir_entries().
        Optionally sort by date or filename.
        """
        filelist = get_dir_entries(self.get_dirpath(req), self.app.archive_dir, dirs=dirs, user=req._user, shortdate=shortdate)
        
        if self.autoload_uploadinfo:
            # Optionally load up the uploadinfo for the files in the list.
            for file in filelist:
                if isinstance(file, FileEntry):
                    (uploads, size) = self.get_uploadinfo(req, file.name)
                    if uploads:
                        file.uploads = uploads
            
        if sort == 'date':
            filelist.sort(key=lambda file:file.date)
        elif sort == 'name':
            filelist.sort(key=lambda file:sortcanon(file.name))
        return filelist

    def get_uploadinfo(self, req, filename):
        """Return a list of UploadEntry records and the file size for a file.
        If the file doesn't exist or is not readable, return (None, None).
        """
        if bad_filename(filename):
            return (None, None)
        pathname = os.path.join(self.get_dirpath(req), filename)
        if not os.path.isfile(pathname):
            return (None, None)
        try:
            stat = os.stat(pathname)
            filesize = stat.st_size
        except Exception as ex:
            return (None, None)

        if not filesize:
            # No point in checking the upload history for zero-length
            # uploads.
            uploads = []
        else:
            hashval = self.app.hasher.get_md5(pathname)
            curs = self.app.getdb().cursor()
            res = curs.execute('SELECT * FROM uploads WHERE md5 = ? ORDER BY uploadtime', (hashval,))
            uploads = [ UploadEntry(tup, user=req._user) for tup in res.fetchall() ]

        for obj in uploads:
            obj.checksuggested(self.app)

        return (uploads, filesize)

    def do_get(self, req):
        """The GET case has to handle download and "show info" links,
        as well as the basic file list.
        """
        self.check_fileops(req)
        view = req.get_query_field('view')
        if view:
            # In this case there will be a "filename" field in the query
            # string. (Not form field -- this is GET, not POST.)
            filename = req.get_query_field('filename')
            if view == 'info':
                return self.do_get_info(req, filename)
            if view == 'dl':
                return self.do_get_download(req, filename)
            raise HTTPError('404 Not Found', 'View "%s" not found: %s' % (view, filename,))
        # Show the list of files and their buttons.
        return self.render(self.template, req)

    def do_get_download(self, req, filename):
        """Handler to download a file within a directory.
        """
        if bad_filename(filename):
            msg = 'Not found: %s' % (filename,)
            raise HTTPError('404 Not Found', msg)
        
        dirpath = self.get_dirpath(req)
        pathname = os.path.join(dirpath, filename)
        if not os.path.isfile(pathname):
            msg = 'Not a file: %s' % (pathname,)
            raise HTTPError('400 Not Readable', msg)
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
        ]
        # The filename has to be encoded according to RFC 5987. But if
        # that's no change, we use the plain version. (Note this takes care
        # of quotes as well as Unicode.)
        encname = urlencode(filename)
        if encname == filename:
            val = 'filename="%s"' % (encname,)
        else:
            # Note no added quotes for this form.
            val = 'filename*=UTF-8\'\'%s' % (encname,)
        response_headers.append( ('Content-Disposition', 'attachment; '+val) )
        
        def resp():
            while True:
                val = fl.read(8192)
                if not val:
                    break
                yield val
            fl.close()
            return
        raise HTTPRawResponse('200 OK', response_headers, resp())
    
    def do_get_info(self, req, filename):
        """Handler to show upload info for a file within a directory.
        """
        (uploads, filesize) = self.get_uploadinfo(req, filename)
        if uploads is None or filesize is None:
            msg = 'Not found: %s' % (filename,)
            raise HTTPError('404 Not Found', msg)

        return self.render('uploadinfo.html', req, filename=filename, filesize=filesize, uploads=uploads)

    def do_post(self, req):
        """The POST case has to handle showing the "confirm/cancel" buttons
        after an operation is selected, and *also* the confirmed operation
        itself.
        """
        self.check_fileops(req)
        view = req.get_query_field('view')
        if view:
            # In this case there will be a "filename" field in the query
            # string. (Not form field.)
            filename = req.get_query_field('filename')
            if view == 'info':
                return self.do_post_info(req, filename)
            raise HTTPError('404 Not Found', 'View "%s" not found: %s' % (view, filename,))
        
        # The operation may be defined by an "op" hidden field or by the
        # button just pressed. (Depending on what stage we're at.)
        if req.get_input_field('op'):
            op = req.get_input_field('op')
        else:
            op = None
            for val in req._fileops:
                if req.get_input_field(val):
                    op = val
                    break
        if not op or op not in req._fileops:
            return self.render(self.template, req,
                               formerror='Invalid operation: %s' % (op,))

        dirpath = self.get_dirpath(req)

        filename = req.get_input_field('filename')
        if filename == '.':
            ent = None   # directory operation
        else:
            if op == 'dellink':
                ent = self.get_symlink(filename, req)
            elif op == 'linkto':
                ent = self.get_file(filename, req)
                if ent is None:
                    ent = self.get_dirent(filename, req)
            elif op == 'rename':
                ent = self.get_file(filename, req)
                if ent is None:
                    ent = self.get_symlink(filename, req)
            else:
                ent = self.get_file(filename, req)
            if not ent:
                return self.render(self.template, req,
                                   formerror='File not found: "%s"' % (filename,))
        # ent is not actually used after this point, though. It was just a check.

        # On any Cancel button, we redirect back to the GET for this page.
        if req.get_input_field('cancel'):
            raise HTTPRedirectPost(self.app.approot+req.path_info+'#list_'+urlencode(filename))

        # If neither "confirm" nor "cancel" was pressed, we're at the
        # stage of showing those buttons. (And also the "rename" input
        # field, etc.) Render the template with those controls showing.
        # "opfile" will be the highlighted file.
        if not req.get_input_field('confirm'):
            # These args are only meaningful for the "move" op.
            movedestorig = None
            movedestgood = None
            delparentdir = None
            delchilddir = None
            ziptoo = None
            if op == 'move' and self.get_dirname(req) == 'unprocessed':
                # This is messy, but the plan is to look up the
                # "suggested" dir for this file and then check whether
                # it's a valid Archive dir. Set movedestorig to the suggested
                # value; set movedestgood to the fill value (minus "arch")
                # if it's valid.
                try:
                    origpath = os.path.join(dirpath, filename)
                    origmd5 = self.app.hasher.get_md5(origpath)
                    curs = self.app.getdb().cursor()
                    res = curs.execute('SELECT * FROM uploads where md5 = ?', (origmd5,))
                    tup = res.fetchone()
                    if tup:
                        ent = UploadEntry(tup)
                        movedestorig = ent.suggestdir
                        ent.checksuggested(self.app)
                        if ent.suggestdiruri and ent.suggestdiruri.startswith('arch/'):
                            movedestgood = ent.suggestdiruri[5:]
                except:
                    pass
            if op == 'deldir':
                # More mess; we need to split the dirname into parent
                # and child. This should always we possible, as we only
                # permit deletion of dirs second-level and deeper.
                val = self.get_dirname(req)
                delparentdir, _, delchilddir = val.rpartition('/')
            if op == 'uncache':
                # Check the filename for zip-ness.
                ziptoo = filename.lower().endswith('.zip')
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               movedestorig=movedestorig,
                               movedestgood=movedestgood,
                               delparentdir=delparentdir,
                               delchilddir=delchilddir,
                               ziptoo=ziptoo)

        # The "confirm" button was pressed, so it's time to perform the
        # action.
        
        if op == 'delete':
            return self.do_post_delete(req, dirpath, filename)
        elif op == 'dellink':
            return self.do_post_dellink(req, dirpath, filename)
        elif op == 'linkto':
            return self.do_post_linkto(req, dirpath, filename)
        elif op == 'move':
            return self.do_post_move(req, dirpath, filename)
        elif op == 'rename':
            return self.do_post_rename(req, dirpath, filename)
        elif op == 'zip':
            return self.do_post_zip(req, dirpath, filename)
        elif op == 'uncache':
            return self.do_post_uncache(req, dirpath, filename)
        elif op == 'csubdir':
            return self.do_post_csubdir(req, dirpath)
        elif op == 'deldir':
            subdirname = req.get_input_field('subdirname')
            return self.do_post_deldir(req, dirpath, subdirname)
        else:
            return self.render(self.template, req,
                               formerror='Operation not implemented: %s' % (op,))

    def do_post_info(self, req, filename):
        """Like do_post(), but for the ?view=info case.
        This duplicates the structure of do_post(), which is annoyingly
        redundant. But it also avoids a bunch of fiddly special cases.
        """
        (uploads, filesize) = self.get_uploadinfo(req, filename)
        if uploads is None or filesize is None:
            msg = 'Not found: %s' % (filename,)
            raise HTTPError('404 Not Found', msg)

        # Note that we do not check fileops! The "Add Note" button does
        # not require a role check; it's always available.
        
        # On any Cancel button, we redirect back to the GET for this page.
        if req.get_input_field('cancel'):
            raise HTTPRedirectPost(self.app.approot+req.path_info+'?view=info&filename='+urlencode(filename))

        if req.get_input_field('op'):
            op = req.get_input_field('op')
        else:
            op = None
            if req.get_input_field('addusernote'):
                op = 'addusernote'
            elif req.get_input_field('notifyifdb'):
                op = 'notifyifdb'
        if not op:
            return self.render('uploadinfo.html', req, filename=filename, filesize=filesize, uploads=uploads,
                               formerror='Invalid operation: %s' % (op,))
            
        # If neither "confirm" nor "cancel" was pressed, we're at the
        # stage of showing those buttons.
        if not req.get_input_field('confirm'):
            return self.render('uploadinfo.html', req,
                               op=op,
                               filename=filename, filesize=filesize, uploads=uploads)
            
        # The "confirm" button was pressed, so it's time to perform the
        # action.
        
        if op == 'addusernote':
            return self.do_post_addusernote(req, filename, uploads, filesize)
        elif op == 'notifyifdb':
            return self.do_post_notifyifdb(req, filename, uploads, filesize)
        else:
            return self.render('uploadinfo.html', req,
                               op=op,
                               filename=filename, filesize=filesize, uploads=uploads,
                               formerror='Operation not implemented: %s' % (op,))

    def do_post_delete(self, req, dirpath, filename):
        """Handle a delete operation (which is really "move to trash").
        """
        op = 'delete'
        if dirpath == self.app.trash_dir:
            raise Exception('delete op cannot be used in the trash')
        newname = find_unused_filename(filename, self.app.trash_dir)
        origpath = os.path.join(dirpath, filename)
        newpath = os.path.join(self.app.trash_dir, newname)

        if not os.path.isfile(origpath):
            raise Exception('delete op requires a file')
        
        shutil.move(origpath, newpath)
        try:
            os.utime(newpath)
        except:
            req.loginfo('Unable to touch timestamp for "%s", continuing delete...' % (filename,))

        # See if we need to delete an Index entry as well.
        dirname = self.get_dirname(req)
        indexdir = IndexDir(dirname, rootdir=self.app.archive_dir, orblank=True)
        ient = indexdir.getmap().get(filename)
        if ient:
            indexdir.delete(filename)
            self.app.rewrite_indexdir(indexdir)
        
        req.loginfo('Deleted "%s" from /%s', filename, self.get_dirname(req))
        return self.render(self.template, req,
                           diddelete=filename, didnewname=newname,
                           didindextoo=bool(ient))

    def do_post_dellink(self, req, dirpath, filename):
        """Handle a delete-symlink operation (which really is delete; we
        don't put symlinks in the trash).
        """
        op = 'dellink'
    
        origpath = os.path.join(dirpath, filename)
        if not os.path.islink(origpath):
            raise Exception('dellink op requires a symlink')

        os.remove(origpath)

        # See if we need to delete an Index entry as well.
        dirname = self.get_dirname(req)
        indexdir = IndexDir(dirname, rootdir=self.app.archive_dir, orblank=True)
        ient = indexdir.getmap().get(filename)
        if ient:
            indexdir.delete(filename)
            self.app.rewrite_indexdir(indexdir)
        
        req.loginfo('Deleted symlink "%s" from /%s', filename, self.get_dirname(req))
        return self.render(self.template, req,
                           diddellink=filename,
                           didindextoo=bool(ient))
        
    def do_post_linkto(self, req, dirpath, filename):
        """Handle a create-symlink operation.
        """
        op = 'linkto'
        destdir = req.get_input_field('destination')
        if not destdir:
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               selecterror='You must select a directory.')

        newdir = destdir
        if newdir.startswith('/'):
            newdir = newdir[ 1 : ]
        if newdir.startswith('if-archive/'):
            newdir = newdir[ 11 : ]
        try:
            newdir = canon_archivedir(newdir, archivedir=req.app.archive_dir)
        except FileConsistency as ex:
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               selecterror='Not an Archive directory: %s' % (newdir,))
        
        if not newdir:
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               selecterror='You cannot create symlinks in the Archive root.')
        if newdir == 'unprocessed':
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               selecterror='You cannot create symlinks in /unprocessed.')

        dirname = self.get_dirname(req)
        
        if newdir == dirname:
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               selecterror='You are already in %s!' % (newdir,))

        origpath = os.path.join(dirpath, filename)
        if os.path.islink(origpath):
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               selecterror='You cannot link to a link!')
        origtype = '???'
        if os.path.isfile(origpath):
            origtype = 'file'
        if os.path.isdir(origpath):
            origtype = 'subdir'
        
        newpath = os.path.join(self.app.archive_dir, newdir, filename)
        if os.path.exists(newpath):
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               selecterror='The %s directory already contains %s.' % (newdir, filename))
            
        relpath = os.path.relpath(origpath, start=os.path.join(self.app.archive_dir, newdir))
        os.symlink(relpath, newpath)

        # See if we need to clone an Index entry.
        indexdir = IndexDir(dirname, rootdir=self.app.archive_dir, orblank=True)
        ient = indexdir.getmap().get(filename)
        if ient:
            indexdir2 = IndexDir(newdir, rootdir=self.app.archive_dir, orblank=True)
            indexdir2.add(ient)
            self.app.rewrite_indexdir(indexdir2)
        
        req.loginfo('Created symlink to %s "%s" from /%s to /%s', origtype, filename, self.get_dirname(req), newdir)
        return self.render(self.template, req,
                           didlinkto=filename, didnewdir=newdir, didnewuri='arch/'+newdir,
                           didindextoo=bool(ient))
        
    
    def do_post_move(self, req, dirpath, filename):
        """Handle a move operation. This checks the radio buttons and
        input field to see where you want to move the file.
        """
        op = 'move'
        destopt = req.get_input_field('destopt')
        destdir = req.get_input_field('destination')
        if (not destopt or destopt == 'other') and not destdir:
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               selecterror='You must select a destination.')

        if destopt == 'inc' and destdir:
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               selecterror='You selected both /incoming and %s; which is it?' % (destdir,))
        if destopt == 'unp' and destdir:
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               selecterror='You selected both /unprocessed and %s; which is it?' % (destdir,))
        if destopt and destopt.startswith('dir_') and destdir:
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               selecterror='You selected both %s and %s; which is it?' % (destopt[4:], destdir,))

        if destopt == 'inc':
            # This isn't in the Archive tree, so handle it as a special case.
            # Note that we auto-rename if necessary. (The user might not
            # know what's in /incoming.)
            newname = find_unused_filename(filename, self.app.incoming_dir)
            origpath = os.path.join(dirpath, filename)
            newpath = os.path.join(self.app.incoming_dir, newname)
            shutil.move(origpath, newpath)
            req.loginfo('Moved "%s" from /%s to /incoming', filename, self.get_dirname(req))
            return self.render(self.template, req,
                               didmove=filename, didnewdir='incoming', didnewuri='incoming', didnewname=newname)
        
        if destopt == 'unp':
            newdir = 'unprocessed'
        elif destopt and destopt.startswith('dir_'):
            dirname = self.get_dirname(req)
            newdir = os.path.join(dirname, destopt[4:])
            try:
                newdir = canon_archivedir(newdir, archivedir=req.app.archive_dir)
            except FileConsistency as ex:
                return self.render(self.template, req,
                                   op=op, opfile=filename,
                                   selecterror='Not an Archive directory: %s' % (newdir,))
        else:
            newdir = destdir
            if newdir.startswith('/'):
                newdir = newdir[ 1 : ]
            if newdir.startswith('if-archive/'):
                newdir = newdir[ 11 : ]
            try:
                newdir = canon_archivedir(newdir, archivedir=req.app.archive_dir)
            except FileConsistency as ex:
                return self.render(self.template, req,
                                   op=op, opfile=filename,
                                   selecterror='Not an Archive directory: %s' % (newdir,))
            
        if not newdir:
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               selecterror='You cannot move files to the Archive root.')

        dirname = self.get_dirname(req)
        
        if newdir == dirname:
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               selecterror='You are already in %s!' % (newdir,))

        origpath = os.path.join(dirpath, filename)
        newpath = os.path.join(self.app.archive_dir, newdir, filename)

        if os.path.exists(newpath):
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               selecterror='A file named %s already exists in %s.' % (filename, newdir,))
            
        shutil.move(origpath, newpath)

        # See if we need to move an Index entry as well.
        indexdir = IndexDir(dirname, rootdir=self.app.archive_dir, orblank=True)
        ient = indexdir.getmap().get(filename)
        if ient:
            indexdir2 = IndexDir(newdir, rootdir=self.app.archive_dir, orblank=True)
            indexdir2.add(ient)
            indexdir.delete(filename)
            self.app.rewrite_indexdir(indexdir2)
            self.app.rewrite_indexdir(indexdir)
        
        req.loginfo('Moved "%s" from /%s to /%s', filename, self.get_dirname(req), newdir)
        return self.render(self.template, req,
                               didmove=filename, didnewdir=newdir, didnewuri='arch/'+newdir,
                           didindextoo=bool(ient))
        
    def do_post_rename(self, req, dirpath, filename):
        """Handle a rename operation. This checks the input field to see
        what you want to rename the file to.
        """
        op = 'rename'
        newname = req.get_input_field('newname')
        if newname is not None:
            newname = newname.strip()
        if not newname:
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               selecterror='You must supply a filename.')
        if bad_filename(newname):
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               selecterror='Invalid filename: "%s"' % (newname,))
        if newname in FileEntry.specialnames:
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               selecterror='Cannot use reserved filename: "%s"' % (newname,))
        origpath = os.path.join(dirpath, filename)
        newpath = os.path.join(dirpath, newname)
        if os.path.exists(newpath):
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               selecterror='Filename already in use: "%s"' % (newname,))
        
        shutil.move(origpath, newpath)
        
        # See if we need to rename an Index entry as well.
        dirname = self.get_dirname(req)
        indexdir = IndexDir(dirname, rootdir=self.app.archive_dir, orblank=True)
        ient = indexdir.getmap().get(filename)
        if ient:
            ient.filename = newname
            self.app.rewrite_indexdir(indexdir)
        
        req.loginfo('Renamed "%s" to "%s" in /%s', filename, newname, self.get_dirname(req))
        return self.render(self.template, req,
                           didrename=filename, didnewname=newname,
                           didindextoo=bool(ient))
        
    def do_post_zip(self, req, dirpath, filename):
        """Handle a zip-up-file operation.
        """
        op = 'zip'
        newname, newsuffix = os.path.splitext(filename)
        newname += '.zip'
        origpath = os.path.join(dirpath, filename)
        newpath = os.path.join(dirpath, newname)
        if os.path.exists(newpath):
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               selecterror='File already exists: "%s"' % (newname,))
        origmd5 = self.app.hasher.get_md5(origpath)
        zip_compress(origpath, newpath)

        # Now move the original to the trash.
        if dirpath != 'trash':
            trashname = find_unused_filename(filename, self.app.trash_dir)
            trashpath = os.path.join(self.app.trash_dir, trashname)
            shutil.move(origpath, trashpath)
            try:
                os.utime(trashpath)
            except:
                req.loginfo('Unable to touch timestamp for "%s", continuing zip...' % (filename,))

        # Now create a new upload entry with the new md5.
        newmd5, newsize = self.app.hasher.get_md5_size(newpath)
        curs = self.app.getdb().cursor()
        res = curs.execute('SELECT * FROM uploads where md5 = ?', (origmd5,))
        for tup in list(res.fetchall()):
            ent = UploadEntry(tup)
            curs.execute('INSERT INTO uploads (uploadtime, md5, size, filename, origfilename, donorname, donoremail, donorip, donoruseragent, permission, suggestdir, ifdbid, about, usernotes, tuid) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (ent.uploadtime, newmd5, newsize, newname, ent.origfilename, ent.donorname, ent.donoremail, ent.donorip, ent.donoruseragent, ent.permission, ent.suggestdir, ent.ifdbid, ent.about, ent.usernotes, ent.tuid))

        req.loginfo('Zipped "%s" to "%s" in /%s', filename, newname, self.get_dirname(req))
        return self.render(self.template, req,
                           didzip=filename, didnewname=newname)

    def do_post_uncache(self, req, dirpath, filename):
        """Handle a cache-purge operation.
        """
        op = 'uncache'

        dirname = self.get_dirname(req)
        ziptoo = filename.lower().endswith('.zip')
        
        try:
            args = [ self.app.uncache_script_path ]
            if ziptoo:
                args.append('--zip')
            args.append('if-archive/%s/%s' % (dirname, filename,))
            if self.app.secure_site:
                args.insert(0, '/usr/bin/sudo')
            subprocess.run(args, check=True, text=True, capture_output=True)
        except subprocess.CalledProcessError as ex:
            errortext = ''
            if ex.stdout:
                errortext += ex.stdout
            if ex.stderr:
                errortext += ex.stderr
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               ziptoo=ziptoo,
                               selecterror='Error: %s\n%s' % (ex, errortext))
        except Exception as ex:
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               ziptoo=ziptoo,
                               selecterror='Error: %s' % (ex,))
            
        req.loginfo('Cache-wiped "%s" in /%s', filename, self.get_dirname(req))
        return self.render(self.template, req,
                           diduncache=filename, ziptoo=ziptoo)

    def do_post_csubdir(self, req, dirpath):
        """Handle a create-subdir operation.
        """
        op = 'csubdir'

        newname = req.get_input_field('newname')
        if newname is not None:
            newname = newname.strip()
        if not newname:
            return self.render(self.template, req,
                               op=op, opfile='.',
                               selecterror='You must supply a directory name.')
        if bad_filename(newname):
            return self.render(self.template, req,
                               op=op, opfile='.',
                               selecterror='Invalid dirname: "%s"' % (newname,))
        if newname in FileEntry.specialnames:
            return self.render(self.template, req,
                               op=op, opfile='.',
                               selecterror='Cannot use reserved filename: "%s"' % (newname,))
        newpath = os.path.join(dirpath, newname)
        if os.path.exists(newpath):
            return self.render(self.template, req,
                               op=op, opfile='.',
                               selecterror='Filename already in use: "%s"' % (newname,))

        os.mkdir(newpath)
        
        req.loginfo('Created subdirectory "%s" in /%s', newname, self.get_dirname(req))
        return self.render(self.template, req,
                           didcsubdir='.', didnewname=newname)
        
    def do_post_deldir(self, req, dirpath, subdir):
        """Handle a delete-directory operation.
        """
        op = 'deldir'

        subdirname = self.get_dirname(req)+'/'+subdir
        subdirpath = os.path.join(self.get_dirpath(req), subdir)

        # Errors from this point don't use selecterror, because we've jumped to the parent directory.
        if not os.path.isdir(subdirpath):
            return self.render(self.template, req,
                               formerror='Directory does not exist: "%s"' % (subdirname,))

        ls = get_dir_entries(subdirpath, self.app.archive_dir, dirs=True)
        if not dir_is_empty(ls):
            namels = [ ent.name for ent in ls ]
            namestr = ', '.join(namels)
            return self.render(self.template, req,
                               formerror='Directory "%s" is not empty, must first delete: %s' % (subdirname, namestr))

        # There may be file entries, but they're all zero-length. Delete them.
        for ent in ls:
            if isinstance(ent, FileEntry) and ent.size == 0:
                delpath = os.path.join(subdirpath, ent.name)
                req.loginfo('Deleted empty file "%s" in /%s', ent.name, subdirname)
                os.remove(delpath)

        # And the directory itself.
        os.rmdir(subdirpath)
            
        req.loginfo('Deleted directory /%s', subdirname)
        return self.render(self.template, req,
                           diddeldir='.', didnewname=subdirname)

    def do_post_addusernote(self, req, filename, uploads, filesize):
        """Handle the add-admin-note operation.
        """
        op = 'addusernote'
        
        note = req.get_input_field('usernote')
        if note:
            note = note.strip()
        if not note:
            return self.render('uploadinfo.html', req,
                               op=op,
                               filename=filename, filesize=filesize, uploads=uploads,
                               formerror='You must supply a line of text.')
        # Add the username.
        note = req._user.name+': '+note

        if uploads:
            # Existing upload records.
            # We are assuming that every upload record for this md5 has the
            # same usernote info. (Other fields may differ! But usernotes
            # are updated by md5, so they should all match.)
            hashval = uploads[0].md5
            val = uploads[0].usernotes
            if not val:
                newnotes = note
            else:
                newnotes = val.strip() + '\n' + note
                
            curs = self.app.getdb().cursor()
            curs.execute('UPDATE uploads SET usernotes = ? WHERE md5 = ?', (newnotes, hashval))

        else:
            # We must create a new upload record.
            # Extract an md5 directly from the file.
            newpath = os.path.join(self.get_dirpath(req), filename)
            hashval, hashsize = self.app.hasher.get_md5_size(newpath)
            if not hashsize:
                return self.render('uploadinfo.html', req,
                                   op=op,
                                   filename=filename, filesize=filesize, uploads=uploads,
                                   formerror='This is a zero-length file, so you cannot add a note.')
            stat = os.stat(newpath)
            uploadtime = int(stat.st_mtime)
            newnotes = note

            curs = self.app.getdb().cursor()
            curs.execute('INSERT INTO uploads (uploadtime, md5, size, filename, origfilename, permission, usernotes) VALUES (?, ?, ?, ?, ?, ?, ?)', (uploadtime, hashval, hashsize, filename, filename, 'unknown', newnotes))

        # Gotta reload to see the change.
        (uploads, filesize) = self.get_uploadinfo(req, filename)
        
        req.loginfo('Added usernote to "%s" from /%s: "%s"', filename, self.get_dirname(req), note)
        return self.render('uploadinfo.html', req, filename=filename, filesize=filesize, uploads=uploads)
        
    def do_post_notifyifdb(self, req, filename, uploads, filesize):
        """Handle notifying IFDB about a file location. (Used to be the
        ifdbize.py script.)
        """
        op = 'notifyifdb'
        
        ifdbid = req.get_input_field('ifdbid')
        if not ifdbid:
            return self.render('uploadinfo.html', req,
                               op=op,
                               filename=filename, filesize=filesize, uploads=uploads,
                               formerror='You must select an IFDB ID to send.')

        # These can each have multiple values
        tuids = req.input.get('tuid')
        orignames = req.input.get('origfilename')

        ifdburl = 'https://ifdb.org/ifarchive-commit'
        ifdbpath = os.path.join('if-archive', self.get_dirname(req), filename)

        # IFDB IDs and the commit key should be alphanumeric.
        urltofetch = '%s?ifdbid=%s&path=%s&key=%s' % (
            ifdburl,
            ifdbid,
            urlencode(ifdbpath),
            self.app.ifdb_commit_key)
        if tuids:
            for tuid in tuids:
                urltofetch += '&tuid=%s' % (tuid,)
        if orignames:
            for origname in orignames:
                urltofetch += '&original_filename=%s' % (urlencode(origname),)

        urlreq = urllib.request.Request(urltofetch)
        urlreq.add_header('User-Agent', 'IFArchive-Admintool')
        
        try:
            ifdbreq = urllib.request.urlopen(urlreq)
            reqresult = ifdbreq.read()
            ifdbreq.close()
            reqresult = reqresult.decode()
        except urllib.error.HTTPError as ex:
            reqresult = str(ex)
            try:
                exmsg = ex.fp.read().decode()
                if exmsg:
                    reqresult = reqresult + '\n' + exmsg
            except:
                pass
        except Exception as ex:
            reqresult = str(ex)

        req.loginfo('Notified IFDB about "%s" (temp ID "%s") being in /%s: "%s"', filename, ifdbid, self.get_dirname(req), reqresult.replace('\n', ' '))
        return self.render('uploadinfo.html', req, filename=filename, filesize=filesize, uploads=uploads,
                           didnotifyifdb=True, ifdbid=ifdbid, reqresult=reqresult)


@beforeall(require_role('incoming'))
class han_Incoming(base_DirectoryPage):
    renderparams = {
        'navtab': 'incoming',
        'uribase': 'incoming',
    }
    template = 'incoming.html'
    autoload_uploadinfo = True

    def add_renderparams(self, req, map):
        # Sorry about the special case.
        unproccount = len([ ent for ent in os.scandir(self.app.unprocessed_dir) if ent.is_file() and ent.name != '.listing' ])
        
        map['dirname'] = self.get_dirname(req)
        map['fileops'] = req._fileops
        map['unproccount'] = unproccount
        map['files'] = self.get_filelist(req, shortdate=True, sort='date')
        return map

    def get_fileops(self, req):
        if req._user.has_role('incoming'):
            return ['move', 'rename', 'delete', 'zip']

    def get_dirname(self, req):
        return 'incoming'

    def get_dirpath(self, req):
        return self.app.incoming_dir


@beforeall(require_role('incoming', 'index'))
class han_Trash(base_DirectoryPage):
    renderparams = {
        'navtab': 'trash',
        'uribase': 'trash',
    }
    template = 'trash.html'

    def add_renderparams(self, req, map):
        map['dirname'] = self.get_dirname(req)
        map['fileops'] = req._fileops
        map['files'] = self.get_filelist(req, shortdate=True, sort='date')
        return map

    def get_fileops(self, req):
        if req._user.has_role('incoming'):
            return ['move', 'rename']

    def get_dirname(self, req):
        return 'trash'

    def get_dirpath(self, req):
        return self.app.trash_dir


@beforeall(require_user)
class han_Unprocessed(base_DirectoryPage):
    renderparams = {
        'navtab': 'unprocessed',
        'uribase': 'arch/unprocessed',
    }
    template = 'unprocessed.html'
    autoload_uploadinfo = True

    def add_renderparams(self, req, map):
        map['dirname'] = self.get_dirname(req)
        map['fileops'] = req._fileops
        map['files'] = self.get_filelist(req, shortdate=True, sort='date')
        map['incomingcount'] = self.get_incomingcount(req)
        return map

    def get_fileops(self, req):
        if req._user.has_role('incoming', 'filing'):
            return ['delete', 'move', 'rename', 'uncache']

    def get_dirname(self, req):
        return 'unprocessed'

    def get_dirpath(self, req):
        return self.app.unprocessed_dir

    def get_incomingcount(self, req):
        count = len([ ent for ent in os.scandir(self.app.incoming_dir) if ent.is_file() ])
        return count

def check_archive_dir(req, han):
    """Request filter which checks the "dir" element of a URI match.
    (This is the (?P<dir>.+) part of the handler spec.) We make sure it's
    a valid archive directory and set req._dirname for future reference.
    
    While we're checking, we also redirect ".../games/" to ".../games"
    (removing the trailing directory slash). This avoids some canonical-dir
    questions.
    """
    dirname = req.match.groupdict()['dir']
    if dirname.endswith('/'):
        dirname = dirname[ : -1 ]
        if not dirname:
            raise HTTPRedirectPost(req.app.approot+'/arch')
        else:
            raise HTTPRedirectPost(req.app.approot+'/arch/'+dirname)
        
    if not dirname:
        req._dirname = ''
        return han(req)

    try:
        val = canon_archivedir(dirname, archivedir=req.app.archive_dir)
    except FileConsistency as ex:
        raise HTTPError('404 Not Found', str(ex))
    
    req._dirname = val
    return han(req)

@beforeall(require_user)
@beforeall(check_archive_dir)
class han_ArchiveDir(base_DirectoryPage):
    renderparams = {
        'navtab': 'archive',
    }
    template = 'archivedir.html'

    def add_renderparams(self, req, map):
        map['dirname'] = self.get_dirname(req)
        map['fileops'] = req._fileops
        if not req._dirname:
            map['uribase'] = 'arch'
        else:
            map['uribase'] = 'arch/' + req._dirname
        ls = self.get_filelist(req, dirs=True, sort='name')
        map['emptydir'] = dir_is_empty(ls)

        indexdir = None
        indexpath = os.path.join(self.get_dirpath(req), 'Index')
        if req._dirname and os.path.isfile(indexpath):
            indexdir = IndexDir(map['dirname'], rootdir=self.app.archive_dir)
            
        map['indexdir'] = indexdir
        if indexdir:
            if indexdir.description:
                map['indexdirdesc'] = indexdir.description.strip()
            map['indexdirmeta'] = indexdir.metadata
            update_file_entries(ls, indexdir, user=req._user)

        map['files'] = [ ent for ent in ls if ent.isfile ]
        dirls = [ ent for ent in ls if ent.isdir ]
        dirls.sort(key=lambda ent:sortcanon(ent.name))
        map['subdirs'] = dirls
            
        return map

    def get_fileops(self, req):
        ls = []
        if req._user.has_role('filing'):
            ls = ['rename', 'delete', 'dellink', 'move', 'linkto', 'csubdir', 'deldir', 'uncache', 'notifyifdb']
        if req._user.has_role('index'):
            ls.append('eindex')
        return ls

    def get_dirname(self, req):
        if not req._dirname:
            return ''
        else:
            return req._dirname
            
    def get_dirpath(self, req):
        if not req._dirname:
            return self.app.archive_dir
        else:
            return os.path.join(self.app.archive_dir, req._dirname)


@beforeall(require_user)
class han_ArchiveRoot(base_DirectoryPage):
    renderparams = {
        'navtab': 'archive',
    }
    template = 'archivedir.html'

    def add_renderparams(self, req, map):
        map['dirname'] = self.get_dirname(req)
        map['fileops'] = req._fileops
        map['uribase'] = 'arch'
        map['dirname'] = ''
        map['isroot'] = True
        ls = self.get_filelist(req, dirs=True, sort='name')
        map['emptydir'] = False

        indexdir = None
        indexpath = os.path.join(self.get_dirpath(req), 'Index')
        if os.path.isfile(indexpath):
            indexdir = IndexDir(map['dirname'], rootdir=self.app.archive_dir)
            
        map['indexdir'] = indexdir
        if indexdir:
            if indexdir.description:
                map['indexdirdesc'] = indexdir.description.strip()
            map['indexdirmeta'] = indexdir.metadata
            update_file_entries(ls, indexdir, user=req._user)

        map['files'] = [ ent for ent in ls if ent.isfile ]
        dirls = [ ent for ent in ls if ent.isdir ]
        dirls.sort(key=lambda ent:sortcanon(ent.name))
        map['subdirs'] = dirls
        
        return map

    def get_fileops(self, req):
        ls = []
        if req._user.has_role('index'):
            ls.append('eindex')
        return ls

    def get_dirname(self, req):
        return ''
            
    def get_dirpath(self, req):
        return self.app.archive_dir


@beforeall(require_role('index'))
class han_EditIndexFile(AdminHandler):
    def get_indextext(self, dirname):
        """Return the contents and the mod timestamp of a directory's Index
        file. If the file does not exist, returns ('', 0).
        """
        if not dirname:
            indexpath = os.path.join(self.app.archive_dir, 'Index')
        else:
            indexpath = os.path.join(self.app.archive_dir, dirname, 'Index')
        if not os.path.exists(indexpath):
            return ('', 0)
        
        fl = open(indexpath, encoding='utf-8')
        indextext = fl.read()
        fl.close()
        stat = os.stat(indexpath)
        return (indextext, stat.st_mtime)

    def get_indexentry(self, dirname, filename):
        """Return one index entry (description, metadata, metalinecount)
        from an Index file, as well as the owning IndexDir.
        If the Index or file does not exists, returns (i, '', '', 0) where
        i is a blank IndexDir.
        """
        indexdir = IndexDir(dirname, rootdir=self.app.archive_dir, orblank=True)
        ient = indexdir.getmap().get(filename)
        if ient:
            if ient.description:
                desc = ient.description.strip()
            else:
                desc = ''
            metastr = '\n'.join([ '%s: %s' % (key, val,) for (key, val) in ient.metadata ])
            metacount = len(ient.metadata)
        else:
            desc = ''
            metastr = ''
            metacount = 0
        return (indexdir, desc, metastr, metacount)
        
    def do_get(self, req):
        return self.render('editindexreq.html', req)

    def do_post(self, req):
        op = req.get_input_field('op')
        if not op:
            return self.do_post_bare(req)
        elif op == 'editall':
            return self.do_post_editall(req)
        elif op == 'editone':
            return self.do_post_editone(req)
        else:
            return self.render('editindexreq.html', req,
                               formerror='Invalid operation')

    def do_post_bare(self, req):
        """Handle the case where someone pressed the "Edit Index"
        or "Edit Index File" button and we arrived here ready to edit.
        Display either the editindexall or editindexone form,
        depending on whether a filename was supplied.
        """
        dirname = req.get_input_field('filedir', '')
        filename = req.get_input_field('filename')
        
        try:
            if dirname.startswith('/'):
                dirname = dirname[ 1 : ]
            dirname = canon_archivedir(dirname, archivedir=self.app.archive_dir)
        except FileConsistency as ex:
            return self.render('editindexreq.html', req,
                               formerror='Bad directory: %s' % (str(ex),))

        if dirname == 'unprocessed':
            return self.render('editindexreq.html', req,
                               formerror='The Archive /unprocessed directory has no Index file.')

            
        if filename:
            filetype = req.get_input_field('filetype')
            indexdir, desc, metas, metacount = self.get_indexentry(dirname, filename)
            return self.render('editindexone.html', req,
                               description=desc,
                               metadata=metas,
                               metacount=metacount,
                               indextime=int(indexdir.date),
                               dirname=dirname, filename=filename, filetype=filetype)
        else:
            indextext, indextime = self.get_indextext(dirname)
            return self.render('editindexall.html', req,
                               indextext=indextext,
                               indextime=int(indextime),
                               dirname=dirname)

    def do_post_editall(self, req):
        """Handle editing an entire raw Index file.
        """
        dirname = req.get_input_field('dirname')
        modtime = req.get_input_field('indextime', 0)
        archdirname = '/arch/'+dirname if dirname else '/arch'
        
        if req.get_input_field('cancel'):
            raise HTTPRedirectPost(self.app.approot+archdirname)

        if req.get_input_field('revert'):
            indextext, indextime = self.get_indextext(dirname)
            return self.render('editindexall.html', req,
                               indextext=indextext,
                               indextime=int(indextime),
                               dirname=dirname)

        newtext = req.get_input_field('textarea', '')
        newtext = clean_newlines(newtext)

        oldtext, oldtime = self.get_indextext(dirname)
        if newtext == clean_newlines(oldtext):
            # Really we're comparing against the current Index file,
            # not the one the user saw when they hit Edit. So this could
            # show a spurious "no changes to save" error if two users
            # make the exact same change at the same time. Sorry.
            return self.render('editindexall.html', req,
                               indextext=oldtext,
                               indextime=int(oldtime),
                               dirname=dirname,
                               formerror='No changes to save.')

        if int(oldtime) != int(modtime):
            return self.render('editindexall.html', req,
                               indextext=newtext,
                               indextime=int(modtime),
                               dirname=dirname,
                               formerror='Index file has been modified since you began editing!')

        if len(oldtext.strip()):
            # Save a copy of the old text in the trash.
            if dirname:
                trashname = 'Index-%s' % (dirname.replace('/', '-'),)
            else:
                trashname = 'Index-root'
            trashname = find_unused_filename(trashname, dir=self.app.trash_dir)
            trashpath = os.path.join(self.app.trash_dir, trashname)
            outfl = open(trashpath, 'w', encoding='utf-8')
            outfl.write(oldtext)
            outfl.close()

        if dirname:
            newpath = os.path.join(self.app.archive_dir, dirname, 'Index')
        else:
            newpath = os.path.join(self.app.archive_dir, 'Index')
        if not newtext:
            # Delete the Index file entirely.
            if os.path.exists(newpath):
                os.remove(newpath)
                req.loginfo('Deleted Index in /%s' % (dirname,))
        else:
            # Write out the new Index file.
            outfl = open(newpath, 'w', encoding='utf-8')
            outfl.write(newtext)
            outfl.close()
            req.loginfo('Updated Index in /%s' % (dirname,))

        raise HTTPRedirectPost(self.app.approot+archdirname)

    def do_post_editone(self, req):
        """Handle editing one entry in an Index file.
        """
        dirname = req.get_input_field('dirname')
        filename = req.get_input_field('filename')
        filetype = req.get_input_field('filetype')
        modtime = req.get_input_field('indextime', 0)
        archdirname = '/arch/'+dirname if dirname else '/arch'
        
        if req.get_input_field('cancel'):
            raise HTTPRedirectPost(self.app.approot+archdirname+'#list_'+urlencode(filename))

        if req.get_input_field('revert'):
            indexdir, desc, metas, metacount = self.get_indexentry(dirname, filename)
            return self.render('editindexone.html', req,
                               description=desc,
                               metadata=metas,
                               metacount=metacount,
                               indextime=int(indexdir.date),
                               dirname=dirname, filename=filename, filetype=filetype)

        newdesc = req.get_input_field('description', '')
        newmeta = req.get_input_field('metadata', '')
        newdesc = clean_newlines(newdesc, prestrip=True)
        newmeta = clean_newlines(newmeta, prestrip=True)
        
        newmetacount = len([ val for val in newmeta.split('\n') if val.strip() ])

        indexdir, olddesc, oldmeta, oldmetacount = self.get_indexentry(dirname, filename)
        if olddesc.strip() == newdesc.strip() and oldmeta.strip() == newmeta.strip():
            return self.render('editindexone.html', req,
                               indextime=int(modtime),
                               dirname=dirname, filename=filename, filetype=filetype,
                               description=olddesc,
                               metadata=oldmeta,
                               metacount=oldmetacount,
                               formerror='No changes to save.')

        try:
            newmetalines = IndexDir.check_metablock(newmeta)
        except Exception as ex:
            return self.render('editindexone.html', req,
                               indextime=int(modtime),
                               dirname=dirname, filename=filename, filetype=filetype,
                               description=newdesc,
                               metadata=newmeta,
                               metacount=newmetacount,
                               formerror='Metadata error: %s' % (ex,))

        
        
        if int(indexdir.date) != int(modtime):
            return self.render('editindexone.html', req,
                               indextime=int(modtime),
                               dirname=dirname, filename=filename, filetype=filetype,
                               description=newdesc,
                               metadata=newmeta,
                               metacount=newmetacount,
                               formerror='Index file has been modified since you began editing!')

        oldtext, oldtime = self.get_indextext(dirname)
        if len(oldtext.strip()):
            # Save a copy of the old text in the trash.
            if dirname:
                trashname = 'Index-%s' % (dirname.replace('/', '-'),)
            else:
                trashname = 'Index-root'
            trashname = find_unused_filename(trashname, dir=self.app.trash_dir)
            trashpath = os.path.join(self.app.trash_dir, trashname)
            outfl = open(trashpath, 'w', encoding='utf-8')
            outfl.write(oldtext)
            outfl.close()

        indexdir.update(filename, newdesc, newmetalines)

        if not indexdir.hasdata():
            # Delete the Index file entirely.
            newpath = os.path.join(self.app.archive_dir, dirname, 'Index')
            if os.path.exists(newpath):
                os.remove(newpath)
                req.loginfo('Deleted Index in /%s' % (dirname,))
        else:
            # Write out the new Index file.
            indexdir.write()
            req.loginfo('Updated Index entry for "%s" in /%s' % (filename, dirname,))
        
        raise HTTPRedirectPost(self.app.approot+archdirname)

@beforeall(require_role('incoming'))
class han_UploadLog(AdminHandler):
    renderparams = { 'navtab':'uploads', 'uribase':'uploadlog' }

    PAGE_LIMIT = 20

    def do_get(self, req):
        val = req.get_query_field('start')
        if val:
            start = int(val)
        else:
            start = 0
        curs = self.app.getdb().cursor()
        res = curs.execute('SELECT * FROM uploads ORDER BY uploadtime DESC LIMIT ? OFFSET ?', (self.PAGE_LIMIT, start,))
        uploads = [ UploadEntry(tup, user=req._user) for tup in res.fetchall() ]
        for obj in uploads:
            obj.checksuggested(self.app)
        return self.render('uploadlog.html', req,
                           uploads=uploads,
                           start=start, limit=self.PAGE_LIMIT,
                           prevstart=max(0, start-self.PAGE_LIMIT), nextstart=start+self.PAGE_LIMIT)

    
@beforeall(require_role('log'))
class han_AdminLog(AdminHandler):
    renderparams = { 'navtab':'adminlog', 'uribase':'adminlog' }
    
    PAGE_LIMIT = 50
    
    def do_get(self, req):
        val = req.get_query_field('start')
        if val:
            start = int(val)
        else:
            start = 0
        lines = log_files_tail(self.app.log_file_path, count=self.PAGE_LIMIT, start=start)
        return self.render('adminlog.html', req,
                           lines=lines,
                           start=start, limit=self.PAGE_LIMIT,
                           prevstart=max(0, start-self.PAGE_LIMIT), nextstart=start+self.PAGE_LIMIT)

        
@beforeall(require_role('rebuild'))
class han_RebuildIndexes(AdminHandler):

    def do_get(self, req):
        locktime = self.app.get_locktime()
        buildtime, builddesc = self.app.get_buildinfo(user=req._user)
        return self.render('rebuild.html', req,
                           locktime=locktime,
                           buildtime=buildtime, builddesc=builddesc)

    def do_post(self, req):
        locktime = self.app.get_locktime()
        buildtime, builddesc = self.app.get_buildinfo(user=req._user)
        val = req.get_input_field('commit')
        if not val:
            return self.render('rebuild.html', req,
                               locktime=locktime,
                               buildtime=buildtime, builddesc=builddesc,
                               formerror='Button not pressed')
        reqall = req.get_input_field('reqall')

        try:
            args = [ self.app.build_script_path ]
            if self.app.secure_site:
                args.insert(0, '/usr/bin/sudo')
            if reqall:
                args.append('--all')
            subprocess.run(args, check=True, text=True, capture_output=True)
        except subprocess.CalledProcessError as ex:
            errortext = ''
            if ex.stdout:
                errortext += ex.stdout
            if ex.stderr:
                errortext += ex.stderr
            return self.render('rebuild.html', req,
                               locktime=locktime,
                               formerror='Error: %s' % (ex,),
                               errortext=errortext)
        except Exception as ex:
            return self.render('rebuild.html', req,
                               locktime=locktime,
                               formerror='Error: %s' % (ex,))
            
        req.loginfo('Requested %sindex rebuild', ('(total) ' if reqall else ''))
        raise HTTPRedirectPost(self.app.approot)
    
class han_DebugDump(AdminHandler):
    """Display all request information. I used this a lot during testing
    but it should be disabled in production.
    """
    def do_get(self, req):
        req.set_content_type(PLAINTEXT)
        yield 'sys.version: %s\n' % (sys.version,)
        yield 'sys.path: %s\n' % (sys.path,)
        yield '__name__: %s\n' % (__name__,)
        if req.match:
            yield 'match: %s\n' % (req.match,)
            yield 'match.groups: %s\n' % (req.match.groups(),)
            yield 'match.groupdict: %s\n' % (req.match.groupdict(),)
        yield 'getpid=%s\n' % (os.getpid(),)
        yield 'getuid=%s, geteuid=%s, getgid=%s, getegid=%s\n' % (os.getuid(), os.geteuid(), os.getgid(), os.getegid(),)
        yield 'environ:\n'
        for key, val in req.env.items():
            yield '  %s: %s\n' % (key, val,)
        if req.query:
            yield 'query: %s\n' % (req.query,)
        if 'wsgi.input' in req.env:
            val = req.env['wsgi.input'].read()
            yield 'input: %s' % (val,)

# Create the master handler list.
handlers = [
    ('', han_Home),
    ('/logout', han_LogOut),
    ('/user', han_UserProfile),
    ('/user/changepw', han_ChangePW),
    ('/user/changetz', han_ChangeTZ),
    ('/admin', han_AdminAdmin),
    ('/admin/allusers', han_AllUsers),
    ('/admin/allsessions', han_AllSessions),
    ('/admin/hashcache', han_HashCache),
    ('/incoming', han_Incoming),
    ('/trash', han_Trash),
    ('/arch', han_ArchiveRoot),
    ('/arch/unprocessed', han_Unprocessed),
    ('/arch/(?P<dir>.+)', han_ArchiveDir),
    ('/editindex', han_EditIndexFile),
    ('/uploadlog', han_UploadLog),
    ('/adminlog', han_AdminLog),
    ('/rebuild', han_RebuildIndexes),
    #('/debugdump', han_DebugDump),
    #('/debugdump/(?P<arg>.+)', han_DebugDump),
]

appinstance = None
config = None
initlock = threading.Lock()

def create_appinstance(environ):
    """Read the configuration and create the TinyApp instance.
    
    We have to do this when the first application request comes in,
    because the config file location is stored in the WSGI environment,
    which is passed in to application(). (It's *not* in os.environ,
    unless we're calling this from the command line.)
    """
    global config, appinstance

    with initlock:
        # To be extra careful, we do this under a thread lock. (I don't know
        # if application() can be called by two threads at the same time, but
        # let's assume it's possible.)
        
        if appinstance is not None:
            # Another thread did all the work while we were grabbing the lock!
            return
    
        # The config file contains all the paths and settings used by the app.
        # The location is specified by the IFARCHIVE_CONFIG env var (if
        # on the command line) or the "SetEnv IFARCHIVE_CONFIG" line (in the
        # Apache WSGI environment).
        configpath = '/var/ifarchive/lib/ifarch.config'
        configpath = environ.get('IFARCHIVE_CONFIG', configpath)
        if not os.path.isfile(configpath):
            raise Exception('Config file not found: ' + configpath)
        
        config = configparser.ConfigParser()
        config.read(configpath)
        
        # Set up the logging configuration.
        # (WatchedFileHandler allows logrotate to rotate the file out from
        # under it.)
        logfilepath = config['AdminTool']['LogFile']
        loghandler = logging.handlers.WatchedFileHandler(logfilepath)
        logging.basicConfig(
            format = '[%(levelname).1s %(asctime)s] %(message)s',
            datefmt = '%b-%d %H:%M:%S',
            level = logging.INFO,
            handlers = [ loghandler ],
        )
        
        # Create the application instance itself.
        appinstance = AdminApp(config, handlers)

    # Thread lock is released when we exit the "with" block.


def application(environ, start_response):
    """The exported WSGI entry point.
    Normally this would just be appinstance.application, but we need to
    wrap that in order to call create_appinstance().
    """
    if appinstance is None:
        create_appinstance(environ)
    return appinstance.application(environ, start_response)


if __name__ == '__main__':
    import adminlib.cli
    create_appinstance(os.environ)
    adminlib.cli.run(appinstance)
