import re

import jinja2.ext

# Jinja extensions. These must be registered in the getjenv() method
# of AdminApp.
# See: https://jinja.palletsprojects.com/en/3.1.x/extensions/
    
class DelimNumber(jinja2.ext.Extension):
    """Display a number with place separators. E.g "12,345,678".
    If the value is not an integer or str(int), return it unchanged.
    """
    pat_alldigits = re.compile('^[0-9]+$')

    def __init__(self, env):
        env.filters['delimnumber'] = self.delim_number

    @staticmethod
    def delim_number(val):
        val = str(val)
        if not DelimNumber.pat_alldigits.match(val):
            return val
    
        ls = []
        lenv = len(val)
        pos = lenv % 3
        if pos:
            ls.append(val[ 0 : pos ])
        while pos < lenv:
            ls.append(val[ pos : pos+3 ])
            pos += 3
        return ','.join(ls)

class PrettyBytes(jinja2.ext.Extension):
    """Display a number as a file size in human-readable form, e.g.
    "5.26 kB" or "97.20 MB". Units are metric (1000-based).
    """
    
    def __init__(self, env):
        env.filters['prettybytes'] = self.pretty_bytes

    @staticmethod
    def pretty_bytes(val):
        if val < 1000:
            return '%d bytes' % (val,)
        if val < 1000000:
            return '%.2f kB' % (val / 1000,)
        if val < 1000000000:
            return '%.2f MB' % (val / 1000000,)
        if val < 1000000000000:
            return '%.2f GB' % (val / 1000000000,)
        return 'BIGNUM: %s' % (val,)
    
class Pluralize(jinja2.ext.Extension):
    """Display "" or "s", depending on whether the value is 1.
    Or you can pass any two strings to display one of.
    """
    def __init__(self, env):
        env.filters['plural'] = self.pluralize

    @staticmethod
    def pluralize(val, singular='', plural='s'):
        if val == 1 or val == '1':
            return singular
        else:
            return plural
            
        
class SplitURI(jinja2.ext.Extension):
    """Convert an admin tool URI ('arch/books/small') into a list of
    (label, URI) pairs, one pair for each component:
      [ ('Archive', 'arch'), ('books', 'arch/books'), ('small', 'arch/books/small')]
    You can use this to create a slash-separated list of links to
    admin directory pages.
    """
    def __init__(self, env):
        env.filters['splituri'] = self.splituri

    @staticmethod
    def splituri(val):
        ls = val.split('/')
        if not ls:
            return []
        if ls[0] == 'arch':
            res = [ ('Archive', 'arch') ]
            for ix in range(1, len(ls)):
                res.append( (ls[ix], '/'.join(ls[ 0 : ix+1 ])) )
            return res
        return [ (val, val) ]


class AttrList(jinja2.ext.Extension):
    """Given a list of objects, return a list of all the unique
    nonempty obj.attr values.
    The values must be hashable (so that uniqueness makes sense).
    """
    def __init__(self, env):
        env.filters['attrlist'] = self.attrlist

    @staticmethod
    def attrlist(ls, key):
        res = []
        for ent in ls:
            val = getattr(ent, key, None)
            if val:
                res.append(val)
        res = list(set(res))
        return res

            
class AllLatin1(jinja2.ext.Extension):
    """Return True if the input string is all Latin-1 characters. If there's
    higher Unicode, or control characters, return False.
    (Control characters are Latin-1 but they count as "funny-looking",
    which is the real question.)
    """
    pat_alllatin1 = re.compile('^[ -~\xA0-\xFF]*$')
        
    def __init__(self, env):
        env.filters['alllatin1'] = self.alllatin1

    @staticmethod
    def alllatin1(val):
        match = AllLatin1.pat_alllatin1.match(val)
        return bool(match)
    
