import re

from adminlib.util import bad_filename, in_user_time

class FileEntry:
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
    
    def __init__(self, filename, stat, user=None):
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
        
        mtime = in_user_time(user, self.date)
        self.fdate = mtime.strftime('%b %d, %H:%M %Z')

class DirEntry:
    """Represents one subdirectory in a directory.
    """
    def __init__(self, dirname, stat, user=None):
        self.name = dirname
        self.date = stat.st_mtime
        self.islink = False
        self.isdir = True
        self.isfile = False

        mtime = in_user_time(user, self.date)
        self.fdate = mtime.strftime('%b %d, %H:%M %Z')

class SymlinkEntry:
    """Represents one symlink in a directory.
    """
    def __init__(self, filename, target, stat, broken=False, isdir=False, user=None):
        self.name = filename
        self.target = target
        self.date = stat.st_mtime
        self.isdir = isdir
        self.isfile = not isdir
        self.broken = broken
        self.islink = True

        mtime = in_user_time(user, self.date)
        self.fdate = mtime.strftime('%b %d, %H:%M %Z')

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

        mtime = in_user_time(user, uploadtime)
        self.fdate = mtime.strftime('%b %d, %H:%M %Z')
        
