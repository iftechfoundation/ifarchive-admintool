import re
import os.path
from collections import OrderedDict

# A filename header starts with exactly one "#" (an h1 header in Markdown)
filename_pattern = re.compile('^#[^#]')

# These patterns match the rules of metadata lines as defined in the
# Markdown extension:
# https://python-markdown.github.io/extensions/meta_data/
meta_start_pattern = re.compile('^[ ]?[ ]?[ ]?([a-zA-Z0-9_-]+):')
meta_cont_pattern = re.compile('^(    |\\t)')

class IndexDir:
    """Represents the contents of an Index file. This is a bunch of
    IndexFile objects, each with a description and metadata, plus
    possibly description/metadata for the directory itself.
    """
    
    @staticmethod
    def if_present(dirname, rootdir=None):
        """Construct an	IndexDir by reading in an Index	file.
        If the Index is not present, this returns None.
        """
        indexpath = os.path.join(rootdir, dirname, 'Index')
        if not os.path.isfile(indexpath):
            return None
        else:
            return IndexDir(dirname, rootdir=rootdir)
    
    def __init__(self, dirname, rootdir=None):
        """Construct an IndexDir by reading in an Index file.
        If the Index is not present, this throws an exception.
        """
        self.dirname = dirname
        self.indexpath = os.path.join(rootdir, dirname, 'Index')

        self.description = None
        self.desclines = []
        self.metadata = []
        self.files = []

        stat = os.stat(self.indexpath)
        self.date = stat.st_mtime

        # Parse the existing Index file.
        infl = open(self.indexpath, encoding='utf-8')
        curfile = None
        curmetaline = True
        
        for ln in infl.readlines():
            if filename_pattern.match(ln):
                # File entry header.
                filename = ln[1:].strip()
                curfile = IndexFile(filename, self)
                curmetaline = True
                self.files.append(curfile)
                continue
            
            if not curfile:
                if curmetaline is not None:
                    match = meta_start_pattern.match(ln)
                    match2 = meta_cont_pattern.match(ln)
                    if ln.strip() == '':
                        curmetaline = None
                    elif match:
                        # New metadata line
                        curmetaline = match.group(1)
                        val = ln[match.end() : ].strip()
                        self.metadata.append( (curmetaline, val) )
                        continue
                    elif type(curmetaline) is str and match2:
                        val = ln[match2.end() : ].strip()
                        self.metadata.append( (curmetaline, val) )
                        continue
                    else:
                        curmetaline = None
                # We're done with the directory metadata, so this is a directory description line.
                # For consistency, the description will always start with a blank line.
                if len(self.desclines) == 0 and ln.strip() != '':
                    self.desclines.append('\n')
                self.desclines.append(ln)
                continue

            # Part of the file entry.
            if curmetaline is not None:
                match = meta_start_pattern.match(ln)
                match2 = meta_cont_pattern.match(ln)
                if ln.strip() == '':
                    curmetaline = None
                elif match:
                    # New metadata line
                    curmetaline = match.group(1)
                    val = ln[match.end() : ].strip()
                    curfile.metadata.append( (curmetaline, val) )
                    continue
                elif type(curmetaline) is str and match2:
                    val = ln[match2.end() : ].strip()
                    curfile.metadata.append( (curmetaline, val) )
                    continue
                else:
                    curmetaline = None
                # We're done with the metadata, so this is a description line.

            # For consistency, the description will always start with a blank line.
            if len(curfile.desclines) == 0 and ln.strip() != '':
                curfile.desclines.append('\n')
                
            curfile.desclines.append(ln)
            
        infl.close()

        if self.desclines:
            self.description = ''.join(self.desclines)
        for file in self.files:
            if file.desclines:
                file.description = ''.join(file.desclines)

    def __repr__(self):
        return '<IndexDir %s>' % (self.dirname,)

    def getmap(self):
        """Create and return a dict mapping filenames to IndexFile objects.
        The dict also contains a '.' entry for the directory data itself.
        (Note that IndexDir.files does not contain the '.' entry. It's just
        handy for the caller of getmap().)
        """
        map = OrderedDict()
        for file in self.files:
            map[file.filename] = file
        dir = IndexFile('.', self)
        map['.'] = dir
        dir.description = self.description
        dir.desclines = self.desclines
        dir.metadata = self.metadata
        return map
    

class IndexFile:
    """Represents one entry in an Index file. Note that, despite the name,
    this may represent a file, subdirectory, symlink, or even a file
    that does not exist in the directory at all. The Index file doesn't
    distinguish these cases; you have to look at the directory itself.
    """
    
    def __init__(self, filename, dir):
        self.filename = filename
        self.dir = dir
        self.description = None
        self.desclines = []
        self.metadata = []
        
    def __repr__(self):
        return '<IndexFile %s>' % (self.filename,)

