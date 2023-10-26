import re
import os, os.path

from adminlib.util import bad_filename, in_user_time

def formatdate(date, user=None, shortdate=False):
    mtime = in_user_time(user, date)
    if shortdate:
        return mtime.strftime('%b %d, %H:%M %Z')
    else:
        return mtime.strftime('%b %d, %Y')


class ListEntry:
    """Base class for FileEntry, DirEntry, SymlinkEntry.
    Objects in these classes should always have isfile, isdir, and
    islink set, and isdir should be (not isfile). (A link can
    be either.)
    """
    pass

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

    # Some files should be zipped because they potentially contain
    # scripting. (HTML and also SVG.)
    pat_html = re.compile('[.](htm|html|svg)$', re.IGNORECASE)
    
    def __init__(self, filename, stat, user=None, shortdate=False):
        # The user argument says what user to display this file *for*.
        # (We use this to localize the time to their timezone.) If
        # user is not provided, we'll display in UTC.
        self.name = filename
        self.date = stat.st_mtime
        self.size = stat.st_size
        self.isspecial = (filename in self.specialnames)
        self.ishtml = bool(self.pat_html.search(filename))
        self.islink = False
        self.isdir = False
        self.isfile = True
        
        self.fdate = formatdate(self.date, user=user, shortdate=shortdate)

class DirEntry(ListEntry):
    """Represents one subdirectory in a directory.
    """
    def __init__(self, dirname, stat, user=None, shortdate=False):
        self.name = dirname
        self.date = stat.st_mtime
        self.islink = False
        self.isdir = True
        self.isfile = False

        self.fdate = formatdate(self.date, user=user, shortdate=shortdate)

class SymlinkEntry(ListEntry):
    """Represents one symlink in a directory.
    """
    def __init__(self, filename, target, stat, broken=False, isdir=False, realpath=None, user=None, shortdate=False):
        self.name = filename
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
        
