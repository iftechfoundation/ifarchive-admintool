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
    def check_metablock(val):
        """Verify that a chunk of text looks like a block of metadata
        lines (and no other text except whitespace).
        (We're tolerant of whitespace and blank lines. This means we accept
        blocks that *wouldn't* be valid in an Index file metadata segment.
        That's okay; this function is used for parsing the metadata text
        field in a web form.)
        Returns a list of key/value pairs, suitable for use in
        IndexFile.
        This uses similar parsing code to IndexDir.
        """
        res = []
        curmetaline = None
        lines = val.split('\n')
        for ln in lines:
            ln = ln.rstrip()
            if not ln:
                continue
            match = meta_start_pattern.match(ln)
            match2 = meta_cont_pattern.match(ln)
            if match:
                key = curmetaline = match.group(1)
                val = ln[match.end() : ].strip()
                res.append( (curmetaline, val) )
                continue
            if curmetaline and match2:
                val = ln[match2.end() : ].strip()
                res.append( (curmetaline, val) )
                continue
            raise Exception('not a metadata line: '+ln)
        return res
    
    def __init__(self, dirname, rootdir=None, orblank=False):
        """Construct an IndexDir by reading in an Index file.
        If the Index is not present, we throw an exception,
        unless orblank is true, in which case we return an empty
        IndexDir.
        """
        self.dirname = dirname
        self.indexpath = os.path.join(rootdir, dirname, 'Index')

        self.description = None
        self.desclines = []
        self.metadata = []
        self.files = []

        if orblank and not os.path.isfile(self.indexpath):
            self.date = 0
            return
        
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
        return '<IndexDir %s (%s files)>' % (self.dirname, len(self.files),)

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

    def update(self, filename, desc, metadata):
        """Update (or add) a file entry (or directory entry, if filename
        is '.'.)
        We are careful to make sure that the description begins with a
        newline and ends with two newlines. (Or, if blank, is None.)
        This will produce clean formatting when written out.
        Note: we don't set desclines at all. Sorry. Not needed at this
        time.
        """
        desc = desc.rstrip()
        if not desc:
            desc = None
        else:
            while desc.startswith('\n'):
                desc = desc[ 1 : ]
            desc = '\n%s\n\n' % (desc,)

        if filename == '.':
            self.description = desc
            self.desclines = None
            self.metadata = metadata
            return

        for file in self.files:
            if file.filename == filename:
                file.description = desc
                file.desclines = None
                file.metadata = metadata
                return
            
        file = IndexFile(filename, self)
        file.description = desc
        file.metadata = metadata
        self.files.append(file)
        return

    def write(self):
        """Write the contents back out to the Index file.
        """
        outfl = open(self.indexpath+'XXX', 'w', encoding='utf-8')

        # For tidiness, we'll keep track of whether the last thing printed was a blank line (or start of file). This lets us ensure that a "#" line always has a blank before it.
        lastblank = True
        
        if self.metadata:
            for key, val in self.metadata:
                outfl.write('%s: %s\n' % (key, val,))
        if self.description:
            outfl.write(self.description)
            lastblank = (self.description == '\n' or self.description.endswith('\n\n'))
        else:
            outfl.write('\n')
            lastblank = True

        for file in self.files:
            if not lastblank:
                outfl.write('\n')
            outfl.write('# %s\n' % (file.filename,))
            if file.metadata:
                for key, val in file.metadata:
                    outfl.write('%s: %s\n' % (key, val,))
            if file.description:
                outfl.write(file.description)
                lastblank = (file.description == '\n' or file.description.endswith('\n\n'))
            else:
                outfl.write('\n')
                lastblank = True

        outfl.close()

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

