from adminlib.util import bad_filename, in_user_time

class FileEntry:
    def __init__(self, filename, stat, user=None):
        self.name = filename
        self.date = stat.st_mtime
        self.size = stat.st_size
        
        mtime = in_user_time(user, self.date)
        self.fdate = mtime.strftime('%b %d, %H:%M %Z')

class UploadEntry:
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
        
