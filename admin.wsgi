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
import configparser
import logging, logging.handlers


# The config file contains all the paths and settings used by the app.

configpath = '/Users/zarf/src/ifarch/ifarchive-admintool/test.config'
#configpath = '/var/ifarchive/lib/ifarch.config'
config = configparser.ConfigParser()
config.read(configpath)

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

from tinyapp.constants import PLAINTEXT, BINARY
from tinyapp.handler import before, beforeall
from tinyapp.excepts import HTTPError, HTTPRedirectPost, HTTPRawResponse
from tinyapp.util import random_bytes, time_now

from adminlib.admapp import AdminApp, AdminHandler
from adminlib.session import User, Session
from adminlib.session import require_user, require_role
from adminlib.util import bad_filename, in_user_time, clean_newlines
from adminlib.util import read_md5, read_size
from adminlib.util import zip_compress
from adminlib.util import find_unused_filename
from adminlib.util import urlencode
from adminlib.util import canon_archivedir, FileConsistency
from adminlib.info import FileEntry, DirEntry, SymlinkEntry, IndexOnlyEntry, UploadEntry
from adminlib.index import IndexDir
    
# URL handlers...

class han_Home(AdminHandler):
    renderparams = { 'navtab':'top' }
    
    def do_get(self, req):
        if not req._user:
            return self.render('login.html', req)

        incount = len([ ent for ent in os.scandir(self.app.incoming_dir) if ent.is_file() ])
        
        # Sorry about the special case.
        unproccount = len([ ent for ent in os.scandir(self.app.unprocessed_dir) if ent.is_file() and ent.name != '.listing' ])

        return self.render('front.html', req, incount=incount, unproccount=unproccount)

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
        req.set_cookie('sessionid', sessionid, maxage=self.app.max_session_age, httponly=True, secure=self.app.secure_site)
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

    
class base_DirectoryPage(AdminHandler):
    """Base class for all handlers that display a file list.
    This will have subclasses for each directory that has special
    handling. (Incoming, Trash, etc.)
    
    This is rather long and messy because it also handles all the
    buttons that can appear under a file name: Move, Rename, Delete,
    and so on.
    """
    
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
        
    def get_filelist(self, req, dirs=False, shortdate=False, sort=None):
        """Get a list of FileEntries from our directory.
        Include DirEntries if requested.
        SymlinkEntries for files will always be included; for dirs too if
        requested.
        """
        filelist = []
        for ent in os.scandir(self.get_dirpath(req)):
            if ent.is_symlink():
                target = os.readlink(ent)
                path = os.path.realpath(ent.path)
                # By this rule, a link to the root if-archive directory itself will show as broken. Fine.
                if path.startswith(self.app.archive_dir+'/') and os.path.exists(path):
                    relpath = path[ len(self.app.archive_dir)+1 : ]
                    if os.path.isfile(path):
                        stat = os.stat(path)
                        file = SymlinkEntry(ent.name, target, stat, realpath=relpath, isdir=False, user=req._user, shortdate=shortdate)
                        filelist.append(file)
                    elif dirs:
                        dir = SymlinkEntry(ent.name, target, stat, realpath=relpath, isdir=True, user=req._user, shortdate=shortdate)
                        filelist.append(dir)
                else:
                    file = SymlinkEntry(ent.name, target, stat, isdir=False, broken=True, user=req._user, shortdate=shortdate)
                    filelist.append(file)
            elif ent.is_file():
                stat = ent.stat()
                file = FileEntry(ent.name, stat, user=req._user, shortdate=shortdate)
                filelist.append(file)
            elif dirs and ent.is_dir():
                stat = ent.stat()
                dir = DirEntry(ent.name, stat, user=req._user, shortdate=shortdate)
                filelist.append(dir)
        if sort == 'date':
            filelist.sort(key=lambda file:file.date)
        elif sort == 'name':
            filelist.sort(key=lambda file:file.name)
        return filelist

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
    
    def do_get_info(self, req, filename):
        """Handler to show upload info for a file within a directory.
        """
        if bad_filename(filename):
            msg = 'Not found: %s' % (filename,)
            raise HTTPError('404 Not Found', msg)
        pathname = os.path.join(self.get_dirpath(req), filename)
        if not os.path.isfile(pathname):
            msg = 'Not a file: %s' % (pathname,)
            raise HTTPError('400 Not Readable', msg)
        try:
            stat = os.stat(pathname)
            filesize = stat.st_size
        except Exception as ex:
            msg = 'Unable to stat: %s %s' % (pathname, ex,)
            raise HTTPError('400 Not Readable', msg)

        if not filesize:
            # No point in checking the upload history for zero-length
            # uploads.
            uploads = []
        else:
            hashval = read_md5(pathname)
            curs = self.app.getdb().cursor()
            res = curs.execute('SELECT * FROM uploads WHERE md5 = ? ORDER BY uploadtime', (hashval,))
            uploads = [ UploadEntry(tup, user=req._user) for tup in res.fetchall() ]
            
        return self.render('uploadinfo.html', req, filename=filename, filesize=filesize, uploads=uploads)

    def do_post(self, req):
        """The POST case has to handle showing the "confirm/cancel" buttons
        after an operation is selected, and *also* the confirmed operation
        itself.
        """
        self.check_fileops(req)
        dirpath = self.get_dirpath(req)
        
        filename = req.get_input_field('filename')
        ent = self.get_file(filename, req)
        if not ent:
            return self.render(self.template, req,
                               formerror='File not found: "%s"' % (filename,))

        # On any Cancel button, we redirect back to the GET for this page.
        if req.get_input_field('cancel'):
            raise HTTPRedirectPost(self.app.approot+req.path_info+'#list_'+urlencode(filename))

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

        # If neither "confirm" nor "cancel" was pressed, we're at the
        # stage of showing those buttons. (And also the "rename" input
        # field, etc.) Render the template with those controls showing.
        # "opfile" will be the highlighted file.
        if not req.get_input_field('confirm'):
            return self.render(self.template, req,
                               op=op, opfile=filename)

        # The "confirm" button was pressed, so it's time to perform the
        # action.
        
        if op == 'delete':
            return self.do_post_delete(req, dirpath, filename)
        elif op == 'moveu':
            return self.do_post_moveu(req, dirpath, filename)
        elif op == 'movei':
            return self.do_post_movei(req, dirpath, filename)
        elif op == 'rename':
            return self.do_post_rename(req, dirpath, filename)
        elif op == 'zip':
            return self.do_post_zip(req, dirpath, filename)
        else:
            return self.render(self.template, req,
                               formerror='Operation not implemented: %s' % (op,))

    def do_post_delete(self, req, dirpath, filename):
        op = 'delete'
        if dirpath == self.app.trash_dir:
            raise Exception('delete op cannot be used in the trash')
        newname = find_unused_filename(filename, self.app.trash_dir)
        origpath = os.path.join(dirpath, filename)
        newpath = os.path.join(self.app.trash_dir, newname)
        os.rename(origpath, newpath)
        req.loginfo('Deleted "%s" from /%s', filename, self.get_dirname(req))
        return self.render(self.template, req,
                           diddelete=filename, didnewname=newname)
        
    def do_post_moveu(self, req, dirpath, filename):
        op = 'moveu'
        if dirpath == self.app.unprocessed_dir:
            raise Exception('moveu op cannot be used in the unprocessed dir')
        newname = find_unused_filename(filename, self.app.unprocessed_dir)
        origpath = os.path.join(dirpath, filename)
        newpath = os.path.join(self.app.unprocessed_dir, newname)
        os.rename(origpath, newpath)
        req.loginfo('Moved "%s" from /%s to /unprocessed', filename, self.get_dirname(req))
        return self.render(self.template, req,
                           didmoveu=filename, didnewname=newname)

    def do_post_movei(self, req, dirpath, filename):
        op = 'movei'
        if dirpath == self.app.incoming_dir:
            raise Exception('movei op cannot be used in the incoming dir')
        newname = find_unused_filename(filename, self.app.incoming_dir)
        origpath = os.path.join(dirpath, filename)
        newpath = os.path.join(self.app.incoming_dir, newname)
        os.rename(origpath, newpath)
        req.loginfo('Moved "%s" from /%s to /incoming', filename, self.get_dirname(req))
        return self.render(self.template, req,
                           didmovei=filename, didnewname=newname)

    def do_post_rename(self, req, dirpath, filename):
        op = 'rename'
        newname = req.get_input_field('newname')
        if newname is not None:
            newname = newname.strip()
        if not newname:
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               formerror='You must supply a filename.')
        if bad_filename(newname):
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               formerror='Invalid filename: "%s"' % (newname,))
        if newname in FileEntry.specialnames:
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               formerror='Cannot use reserved filename: "%s"' % (newname,))
        origpath = os.path.join(dirpath, filename)
        newpath = os.path.join(dirpath, newname)
        if os.path.exists(newpath):
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               formerror='Filename already in use: "%s"' % (newname,))
        os.rename(origpath, newpath)
        req.loginfo('Renamed "%s" to "%s" in /%s', filename, newname, self.get_dirname(req))
        return self.render(self.template, req,
                           didrename=filename, didnewname=newname)
        
    def do_post_zip(self, req, dirpath, filename):
        op = 'zip'
        newname = filename+'.zip'
        origpath = os.path.join(dirpath, filename)
        newpath = os.path.join(dirpath, newname)
        if os.path.exists(newpath):
            return self.render(self.template, req,
                               op=op, opfile=filename,
                               formerror='File already exists: "%s"' % (newname,))
        origmd5 = read_md5(origpath)
        zip_compress(origpath, newpath)

        # Now create a new upload entry with the new md5.
        newsize = read_size(newpath)
        newmd5 = read_md5(newpath)
        curs = self.app.getdb().cursor()
        res = curs.execute('SELECT * FROM uploads where md5 = ?', (origmd5,))
        for tup in list(res.fetchall()):
            ent = UploadEntry(tup)
            curs.execute('INSERT INTO uploads (uploadtime, md5, size, filename, origfilename, donorname, donoremail, donorip, donoruseragent, permission, suggestdir, ifdbid, about) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (ent.uploadtime, newmd5, newsize, newname, ent.origfilename, ent.donorname, ent.donoremail, ent.donorip, ent.donoruseragent, ent.permission, ent.suggestdir, ent.ifdbid, ent.about))

        req.loginfo('Zipped "%s" to "%s" in /%s', filename, newname, self.get_dirname(req))
        return self.render(self.template, req,
                           didzip=filename, didnewname=newname)


@beforeall(require_role('incoming'))
class han_Incoming(base_DirectoryPage):
    renderparams = {
        'navtab': 'incoming',
        'uribase': 'incoming',
    }
    template = 'incoming.html'

    def add_renderparams(self, req, map):
        map['dirname'] = self.get_dirname(req)
        map['fileops'] = req._fileops
        map['trashcount'] = self.get_trashcount(req)
        map['files'] = self.get_filelist(req, shortdate=True, sort='date')
        return map

    def get_fileops(self, req):
        if req._user.has_role('incoming'):
            return ['moveu', 'rename', 'delete', 'zip']

    def get_dirname(self, req):
        return 'incoming'

    def get_dirpath(self, req):
        return self.app.incoming_dir

    def get_trashcount(self, req):
        count = len([ ent for ent in os.scandir(self.app.trash_dir) if ent.is_file() ])
        return count


@beforeall(require_role('incoming'))
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
            return ['movei', 'moveu', 'rename']

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

    def add_renderparams(self, req, map):
        map['dirname'] = self.get_dirname(req)
        map['fileops'] = req._fileops
        map['files'] = self.get_filelist(req, shortdate=True, sort='date')
        map['incomingcount'] = self.get_incomingcount(req)
        return map

    def get_fileops(self, req):
        if req._user.has_role('incoming'):
            return ['delete', 'movei', 'rename']

    def get_dirname(self, req):
        return 'unprocessed'

    def get_dirpath(self, req):
        return self.app.unprocessed_dir

    def get_incomingcount(self, req):
        count = len([ ent for ent in os.scandir(self.app.incoming_dir) if ent.is_file() ])
        return count

def check_archive_dir(req, han):
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

        indexdir = None
        indexpath = os.path.join(self.get_dirpath(req), 'Index')
        if req._dirname and os.path.isfile(indexpath):
            indexdir = IndexDir(map['dirname'], rootdir=self.app.archive_dir)
            
        map['indexdir'] = indexdir
        if indexdir:
            ifmap = indexdir.getmap()
            # ifnames excludes '.'
            ifnames = set([ ifile.filename for ifile in indexdir.files ])
            if indexdir.description:
                map['indexdirdesc'] = indexdir.description.strip()
            map['indexdirmeta'] = indexdir.metadata

            for ent in ls:
                ifile = ifmap.get(ent.name)
                if ifile:
                    if ifile.description:
                        ent.indexdesc = ifile.description.strip()
                    ent.indexmeta = ifile.metadata
                ifnames.discard(ent.name)

            if ifnames:
                ifnames = list(ifnames)
                ifnames.sort()
                for name in ifnames:
                    ifile = ifmap[name]
                    ent = IndexOnlyEntry(ifile.filename, date=indexdir.date, user=req._user)
                    if ifile.description:
                        ent.indexdesc = ifile.description.strip()
                    ent.indexmeta = ifile.metadata
                    ls.append(ent)

        map['files'] = [ ent for ent in ls if ent.isfile ]
        dirls = [ ent for ent in ls if ent.isdir ]
        dirls.sort(key=lambda ent:ent.name)
        map['subdirs'] = dirls
            
        return map

    def get_fileops(self, req):
        if req._user.has_role('files'):
            return ['rename', 'delete', 'moveu', 'eindex']

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
        map['files'] = [ ent for ent in ls if ent.isfile ]
        dirls = [ ent for ent in ls if ent.isdir ]
        dirls.sort(key=lambda ent:ent.name)
        map['subdirs'] = dirls
        return map

    def get_fileops(self, req):
        return [] ###

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
            desc = ient.description.strip()
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
        dirname = req.get_input_field('filedir', '')
        filename = req.get_input_field('filename')
        
        try:
            if dirname.startswith('/'):
                dirname = dirname[ 1 : ]
            dirname = canon_archivedir(dirname, archivedir=self.app.archive_dir)
        except FileConsistency as ex:
            return self.render('editindexreq.html', req,
                               formerror='Bad directory: %s' % (str(ex),))

        if not dirname:
            return self.render('editindexreq.html', req,
                               formerror='The Archive root directory has no Index file.')
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
        dirname = req.get_input_field('dirname')
        modtime = req.get_input_field('indextime', 0)
        
        if req.get_input_field('cancel'):
            raise HTTPRedirectPost(self.app.approot+'/arch/'+dirname)

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
            trashname = 'Index-%s' % (dirname.replace('/', '-'),)
            trashname = find_unused_filename(trashname, dir=self.app.trash_dir)
            trashpath = os.path.join(self.app.trash_dir, trashname)
            outfl = open(trashpath, 'w', encoding='utf-8')
            outfl.write(oldtext)
            outfl.close()

        newpath = os.path.join(self.app.archive_dir, dirname, 'Index')
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

        raise HTTPRedirectPost(self.app.approot+'/arch/'+dirname)

    def do_post_editone(self, req):
        dirname = req.get_input_field('dirname')
        filename = req.get_input_field('filename')
        filetype = req.get_input_field('filetype')
        modtime = req.get_input_field('indextime', 0)
        
        if req.get_input_field('cancel'):
            raise HTTPRedirectPost(self.app.approot+'/arch/'+dirname+'#list_'+urlencode(filename))

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
                               indextime=int(indexdir.date),
                               dirname=dirname, filename=filename, filetype=filetype,
                               description=olddesc,
                               metadata=oldmeta,
                               metacount=oldmetacount,
                               formerror='No changes to save.')

        try:
            newmetalines = IndexDir.check_metablock(newmeta)
        except Exception as ex:
            return self.render('editindexone.html', req,
                               indextime=int(indexdir.date),
                               dirname=dirname, filename=filename, filetype=filetype,
                               description=newdesc,
                               metadata=newmeta,
                               metacount=newmetacount,
                               formerror='Metadata error: %s' % (ex,))

        
        
        if int(indexdir.date) != int(modtime):
            return self.render('editindexone.html', req,
                               indextime=int(indexdir.date),
                               dirname=dirname, filename=filename, filetype=filetype,
                               description=newdesc,
                               metadata=newmeta,
                               metacount=newmetacount,
                               formerror='Index file has been modified since you began editing!')
        
        return self.render('editindexone.html', req,
                           indextime=int(modtime),
                           dirname=dirname, filename=filename, filetype=filetype,
                           description=newdesc,
                           metadata=newmeta,
                           metacount=newmetacount,
                           formerror='### working')

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
        return self.render('uploadlog.html', req, uploads=uploads, start=start, limit=self.PAGE_LIMIT, prevstart=max(0, start-self.PAGE_LIMIT), nextstart=start+self.PAGE_LIMIT)
    
        
class han_DebugDump(AdminHandler):
    """Display all request information. I used this a lot during testing
    but it should be disabled in production.
    """
    def do_get(self, req):
        req.set_content_type(PLAINTEXT)
        yield 'sys.version: %s\n' % (sys.version,)
        yield 'sys.path: %s\n' % (sys.path,)
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
    ('/incoming', han_Incoming),
    ('/trash', han_Trash),
    ('/arch', han_ArchiveRoot),
    ('/arch/unprocessed', han_Unprocessed),
    ('/arch/(?P<dir>.+)', han_ArchiveDir),
    ('/editindex', han_EditIndexFile),
    ('/uploadlog', han_UploadLog),
    ('/debugdump', han_DebugDump),
    ('/debugdump/(?P<arg>.+)', han_DebugDump),
]

# Create the application instance itself.
appinstance = AdminApp(config, handlers)

# Set up the WSGI entry point.
application = appinstance.application



if __name__ == '__main__':
    import adminlib.cli
    adminlib.cli.run(appinstance)
