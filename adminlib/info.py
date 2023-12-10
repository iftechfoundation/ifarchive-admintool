import re
import os, os.path
import time

from adminlib.util import in_user_time
from adminlib.util import canon_archivedir, FileConsistency

def formatdate(date, user=None, shortdate=False):
    """Format a timestamp into human-readable form. If user is provided,
    we use the user's time zone.
    If shortdate is false, this looks like "Oct 28, 2023".
    If shortdate is true, this looks like "Oct 28, 14:38 EDT", or
    "Oct 28 2022, 14:38 EDT" for dates more than six months in the past.
    The point is to use shortdate=True for date lists where we care about
    the exact time. (E.g. many recent files.) If we only care about the
    historical date, use shortdate=False for a uniform display.
    (Yes, this means "shortdate=False" gives a shorter string than
    "shortdate=True". Sorry, the semantics shifted a bit.)
    """
    mtime = in_user_time(user, date)
    if shortdate:
        if date < time.time() - 15552000:
            return mtime.strftime('%b %d %Y, %H:%M %Z')
        else:
            return mtime.strftime('%b %d, %H:%M %Z')
    else:
        return mtime.strftime('%b %d, %Y')

def get_dir_entries(dirpath, archivedir, dirs=False, user=None, shortdate=False):
    """Get a list of FileEntries from a given directory.
    Include DirEntries if requested.
    SymlinkEntries for files will always be included; for dirs too if
    requested.
    Can supply user and shortdate options (for timestamp formatting).
    """
    filelist = []
    
    for ent in os.scandir(dirpath):
        if ent.is_symlink():
            target = os.readlink(ent)
            path = os.path.realpath(ent.path)
            # By this rule, a link to the root if-archive directory itself will show as broken. Fine.
            if path.startswith(archivedir+'/') and os.path.exists(path):
                relpath = path[ len(archivedir)+1 : ]
                if os.path.isfile(path):
                    stat = os.stat(path)
                    file = SymlinkEntry(ent.name, target, stat, realpath=relpath, isdir=False, user=user, shortdate=shortdate)
                    filelist.append(file)
                elif dirs and os.path.isdir(path):
                    stat = os.stat(path)
                    dir = SymlinkEntry(ent.name, target, stat, realpath=relpath, isdir=True, user=user, shortdate=shortdate)
                    filelist.append(dir)
            else:
                # Gotta use the link's own stat
                stat = os.lstat(ent.path)
                file = SymlinkEntry(ent.name, target, stat, isdir=False, broken=True, user=user, shortdate=shortdate)
                filelist.append(file)
        elif ent.is_file():
            stat = ent.stat()
            file = FileEntry(ent.name, stat, user=user, shortdate=shortdate)
            filelist.append(file)
        elif dirs and ent.is_dir():
            stat = ent.stat()
            dir = DirEntry(ent.name, stat, user=user, shortdate=shortdate)
            filelist.append(dir)

    return filelist
    
def dir_is_empty(ls):
    """Given a list of ListEntry objects, return True if there are no
    directories, symlinks, or nonempty files. (That is, if the directory
    is safe for deletion.)
    """
    if not ls:
        return True
    for ent in ls:
        if isinstance(ent, FileEntry):
            if ent.size:
                return False
        else:
            return False
    return True


class ListEntry:
    """Base class for FileEntry, DirEntry, SymlinkEntry.
    Objects in these classes should always have isfile, isdir, and
    islink set, and isdir should be (not isfile). (A link can
    be either.)
    """
    def __init__(self, name):
        self.name = name
        self.date = None

        # Exactly one of these should wind up set.
        self.isdir = False
        self.isfile = False
        
        self.islink = False

        # For symlinks, isbroken means the target is missing. For files,
        # isbroken means the file is missing (e.g. IndexOnlyEntry).
        self.isbroken = False

        # These may be filled in later.
        self.indexdesc = None
        self.indexmeta = None

class FileEntry(ListEntry):
    """Represents one file in a directory.
    
    FileEntries are used in the templates which display lists of
    files. Note that we don't cache these between requests; they
    are created on the fly for each request.
    """
    
    # Some files have special meaning for the Archive and shouldn't be
    # moved or renamed.
    specialnames = set([
        'Index',
        'Master-Index',
        '.listing',
    ])

    # Some files can be sent to iplayif.com for web play.
    # Most files, really; so many that this pattern is the converse.
    pat_noiplay = re.compile('[.](zip|gz|tgz|txt|text|jpg|jpeg|png|gif|pdf|htm|html|svg)$', re.IGNORECASE)

    # Some files should be zipped because they potentially contain
    # scripting. (HTML and also SVG.)
    pat_html = re.compile('[.](htm|html|svg)$', re.IGNORECASE)
    
    def __init__(self, filename, stat, user=None, shortdate=False):
        ListEntry.__init__(self, filename)
        # The user argument says what user to display this file *for*.
        # (We use this to localize the time to their timezone.) If
        # user is not provided, we'll display in UTC.
        self.date = stat.st_mtime
        self.size = stat.st_size
        self.isspecial = (filename in self.specialnames)
        self.ishtml = bool(self.pat_html.search(filename))
        self.isiplay = not bool(self.pat_noiplay.search(filename))
        self.isfile = True
        
        self.fdate = formatdate(self.date, user=user, shortdate=shortdate)

class DirEntry(ListEntry):
    """Represents one subdirectory in a directory.
    """
    def __init__(self, dirname, stat, user=None, shortdate=False):
        ListEntry.__init__(self, dirname)
        self.date = stat.st_mtime
        self.isdir = True

        self.fdate = formatdate(self.date, user=user, shortdate=shortdate)

class SymlinkEntry(ListEntry):
    """Represents one symlink in a directory.
    The stat argument is the target file, unless the link is broken,
    in which case it's the link itself.
    """
    def __init__(self, filename, target, stat, broken=False, isdir=False, realpath=None, user=None, shortdate=False):
        ListEntry.__init__(self, filename)
        self.target = target
        self.realpath = realpath
        self.date = stat.st_mtime
        self.isdir = isdir
        self.isfile = not isdir
        self.broken = broken
        self.islink = True

        if self.realpath is None:
            self.realuri = None
        else:
            if self.isdir:
                val = self.realpath
            else:
                val = os.path.dirname(self.realpath)
            if val:
                self.realuri = 'arch/'+val
            else:
                self.realuri = 'arch'

        self.fdate = formatdate(self.date, user=user, shortdate=shortdate)

class IndexOnlyEntry(ListEntry):
    """Represents a file that doesn't exist at all (in this directory),
    but which has Index metadata. We want to show these entries in
    the file list, so we need a ListEntry class.
    (We'll pass in the date of the Index file.)
    """
    def __init__(self, filename, date=None, user=None, shortdate=False):
        ListEntry.__init__(self, filename)
        self.date = date
        self.isfile = True
        self.isbroken = True

        self.fdate = formatdate(self.date, user=user, shortdate=shortdate)


class UploadEntry:
    """Represents one entry in the upload log.
    The arguments come straight from the "uploads" DB table.
    
    UploadEntries are used in the templates which display lists of
    upload info. Note that we don't cache these between requests; they
    are created on the fly for each request.
    """
    
    def __init__(self, args, user=None):
        (uploadtime, md5, size, filename, origfilename, donorname, donoremail, donorip, donoruseragent, permission, suggestdir, ifdbid, about) = args
        self.uploadtime = uploadtime
        self.md5 = md5
        self.size = size
        self.filename = filename
        self.origfilename = origfilename
        self.donorname = donorname
        self.donoremail = donoremail
        self.donorip = donorip
        self.donoruseragent = donoruseragent
        self.permission = permission
        self.suggestdir = suggestdir
        self.ifdbid = ifdbid
        self.about = about

        self.fdate = formatdate(uploadtime, user=user, shortdate=True)
        self.suggestdirchecked = False

    def checksuggested(self, app):
        """Check whether the suggested directory exists.
        """
        if self.suggestdir:
            self.suggestdirchecked = True
            val = self.suggestdir
            if val.startswith('/'):
                val = val[ 1 : ]
            if val.startswith('if-archive/'):
                val = val[ 11 : ]
            try:
                val = canon_archivedir(val, archivedir=app.archive_dir)
                if not val:
                    self.suggestdiruri = 'arch'
                else:
                    self.suggestdiruri = 'arch/'+val
            except FileConsistency as ex:
                self.suggestdiruri = None
