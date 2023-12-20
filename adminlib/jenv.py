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


class IFDBIDList(jinja2.ext.Extension):
    """Given a list of UploadEntry items, return a list of all the
    nonempty ifdbid values.
    """
    def __init__(self, env):
        env.filters['ifdbidlist'] = self.ifdbidlist

    @staticmethod
    def ifdbidlist(ls):
        res = [ ent.ifdbid for ent in ls if ent.ifdbid ]
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
    
