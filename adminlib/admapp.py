import time
import os, os.path
import threading
import sqlite3

from jinja2 import Environment, FileSystemLoader, select_autoescape

from tinyapp.app import TinyApp, TinyRequest
from tinyapp.handler import ReqHandler
import tinyapp.auth

from adminlib.session import find_user
from adminlib.info import formatdate
from adminlib.util import find_unused_filename
from adminlib.jenv import DelimNumber, PrettyBytes, Pluralize, AttrList, SplitURI, AllLatin1
from adminlib.hasher import Hasher

class AdminApp(TinyApp):
    """AdminApp: The TinyApp class.
    """
    
    def __init__(self, config, hanclasses):
        # The SecureSite flag comes from the config file. We'll need this
        # for the TinyApp constructor step.
        secureflag = config['DEFAULT'].getboolean('SecureSite')
        cookieprefix = '__Host-' if secureflag else ''
        
        TinyApp.__init__(self, hanclasses, wrapall=[
            tinyapp.auth.xsrf_cookie(cookieprefix+'_xsrf'),
            tinyapp.auth.xsrf_check_post('_xsrf'),
            find_user,
        ], secure_site=secureflag)
        
        # We apply three request filters to every incoming request:
        # - create an XSRF cookie;
        # - check POST requests for the XSRF cookie;
        # - see what user is authenticated based on the session cookie.
        # The secure_site flag gets us more secure cookies.

        self.cookieprefix = cookieprefix
        
        # Pull some (more) settings out of the config file.
        
        self.approot = config['AdminTool']['AppRoot']
        self.incoming_dir = config['DEFAULT']['IncomingDir']
        self.trash_dir = config['DEFAULT']['TrashDir']
        self.archive_dir = config['DEFAULT']['ArchiveDir']
        self.unprocessed_dir = os.path.join(self.archive_dir, 'unprocessed')
        self.ifdb_commit_key = config['DEFAULT']['IFDBCommitKey']

        self.sudo_scripts = config['AdminTool'].getboolean('SudoScripts')
        self.max_session_age = config['AdminTool'].getint('MaxSessionAge')
        self.max_trash_age = config['AdminTool'].getint('MaxTrashAge')

        self.db_path = config['DEFAULT']['DBFile']
        self.build_script_path = config['AdminTool']['BuildScriptFile']
        self.build_lock_path = config['AdminTool']['BuildLockFile']
        self.build_output_path = config['AdminTool']['BuildOutputFile']
        self.uncache_script_path = config['AdminTool']['UncacheScriptFile']
        self.template_path = config['AdminTool']['TemplateDir']
        self.log_file_path = config['AdminTool']['LogFile']
        self.app_css_uri = config['AdminTool']['AppCSSURI']

        # Thread-local storage for various things which are not thread-safe.
        self.threadcache = threading.local()

        # Module for computing (and caching) MD5 checksums. It is thread-safe.
        self.hasher = Hasher()

    def getdb(self):
        """Get or create a sqlite3 db connection object. These are
        cached per-thread.
        (The sqlite3 module is thread-safe, but the db connection objects
        you get from it might not be shareable between threads. Depends on
        the version of SQLite installed, but we take no chances.)
        """
        db = getattr(self.threadcache, 'db', None)
        if db is None:
            db = sqlite3.connect(self.db_path)
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
                loader = FileSystemLoader(self.template_path),
                extensions = [
                    DelimNumber,
                    PrettyBytes,
                    Pluralize,
                    SplitURI,
                    AttrList,
                    AllLatin1,
                ],
                autoescape = select_autoescape(),
                keep_trailing_newline = True,
            )
            jenv.globals['approot'] = self.approot
            jenv.globals['appcssuri'] = self.app_css_uri
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
        # The requri is the absolute URI, excluding domain and #fragment.
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

    def get_locktime(self):
        """Check whether the rebuild-index lock file exists. If it does,
        return its age in seconds. If not, return None.
        (This is used by a couple of handlers, so it's easiest to put
        it here.)
        """
        try:
            stat = os.stat(self.build_lock_path)
            locktime = int(time.time() - stat.st_mtime)
            return locktime
        except:
            return None
        
    def get_buildinfo(self, user=None):
        """Check whether the rebuild-index output file exists.
        If it does, return its timestamp and contents. If not,
        return (None, None).
        (Probably this should be combined with get_locktime(), since it's
        used by exactly the same handlers.)
        """
        try:
            stat = os.stat(self.build_output_path)
            mtime = stat.st_mtime
            time = formatdate(mtime, user=user, shortdate=True)
            fl = open(self.build_output_path)
            dat = fl.read()
            fl.close()
            return (time, dat)
        except:
            return (None, None)

    def rewrite_indexdir(self, indexdir):
        """Write out an IndexDir to a directory, or delete the existing
        Index file if there's nothing to write. We copy the old Index file
        to the trash if there is one.
        """
        dirname = indexdir.dirname
        
        indextext = indexdir.getorigtext()
        if indextext is not None:
            # Save a copy of the old text in the trash.
            trashname = 'Index-%s' % (dirname.replace('/', '-'),)
            trashname = find_unused_filename(trashname, dir=self.trash_dir)
            trashpath = os.path.join(self.trash_dir, trashname)
            outfl = open(trashpath, 'w', encoding='utf-8')
            outfl.write(indextext)
            outfl.close()
        
        if not indexdir.hasdata():
            # Delete the Index file entirely.
            if os.path.exists(indexdir.indexpath):
                os.remove(indexdir.indexpath)
        else:
            # Write out the updated Index.
            indexdir.write()
        

class AdminRequest(TinyRequest):
    """Our app-specific subclass of TinyRequest. This just has a spot
    to stash the current User (as determined by the find_user() filter).
    """
    
    def __init__(self, app, env):
        TinyRequest.__init__(self, app, env)

        # Initialize our app-specific fields.
        self._user = None

    def lognote(self):
        """A string which will appear in any log line generated by this
        request. We show the current User, if any.
        """
        if not self._user:
            return 'user=(none)'
        else:
            return 'user=%s' % (self._user.name,)

class AdminHandler(ReqHandler):
    """Our app-specific subclass of ReqHandler. This knows how to
    render a Jinja template for the current request. (We do that a
    lot, so it's worth having a shortcut.)
    """
    renderparams = None

    def add_renderparams(self, req, map):
        """Some handlers will want to add in template parameters
        on the fly.
        """
        return map
    
    def render(self, template, req, **params):
        """Render a template for the current request. This adds in some
        per-handler template parameters.
        """
        if not self.renderparams:
            map = {}
        else:
            map = dict(self.renderparams)
        map = self.add_renderparams(req, map)
        map.update(params)
        return self.app.render(template, req, **map)
