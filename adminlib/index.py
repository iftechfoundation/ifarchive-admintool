import re
from collections import OrderedDict
import markdown

filename_pattern = re.compile('^#[^#]')
dashline_pattern = re.compile('^[ ]*[-+=#*]+[ -+=#*]*$')

convertermeta = markdown.Markdown(extensions = ['meta'])

class IndexFile:
    def __init__(self, headerlines, files):
        self.files = files
        self.filemap = { file.name:file for file in files }
        self.metadata = OrderedDict()

        headerstr = '\n'.join(headerlines)
        headerstr = headerstr.rstrip() + '\n'
        # Now headerstr starts with zero newlines and ends
        # with one newline.

        anyheader = bool(headerstr.strip())
        if anyheader:
            # Convert Markdown to HTML.
            val = convertermeta.convert(headerstr)
            for (mkey, mls) in convertermeta.Meta.items():
                self.metadata[mkey] = list(mls)
            convertermeta.Meta.clear()

            ### stash val?
            
class IndexFileEntry:
    """One file entry in an Index file.
    """
    def __init__(self, filename):
        self.submap = {}

        self.name = filename
        self.metadata = OrderedDict()

    def __repr__(self):
        return '<IndexFileEntry %s>' % (self.name,)

    def complete(self, desclines):
        # Take the accumulated description text and stick it into our
        # File object.
        if desclines:
            val = '\n'.join(desclines)
            filestr = convertermeta.convert(val)
            for (mkey, mls) in convertermeta.Meta.items():
                self.metadata[mkey] = list(mls)
            convertermeta.Meta.clear()

            ### stash filestr?

    def getmetadata_string(self, key):
        # Return a metadata value as a string. If there are multiple values,
        # just use the first.
        if key not in self.metadata or not self.metadata[key]:
            return None
        return self.metadata[key][0]


def parse_index(pathname):
    infl = open(pathname, encoding='utf-8')

    files = []
    
    filedesclines = None
    inheader = True
    headerlines = []
    file = None
    
    while True:
        ln = infl.readline()
        if not ln:
            if file:
                # Finish constructing the file in progress.
                file.complete(filedesclines)
                file = None
            break
        
        ln = ln.rstrip()

        bx = ln

        if inheader:
            if not filename_pattern.match(bx):
                # Further header lines become part of headerlines.
                headerlines.append(bx)
                continue

            # The header ends when we find a line starting with "#".
            inheader = False
            file = None

        if filename_pattern.match(bx):
            # Start of a new file block.

            if file:
                # Finish constructing the file in progress.
                file.complete(filedesclines)
                file = None

            # Set up the new file, including a fresh filedesclines
            # accumulator.

            filename = bx[2:].strip()
            bx = ''
            filedesclines = []
                
            file = IndexFileEntry(filename)
            files.append(file)

        else:
            # Continuing a file block.
            filedesclines.append(bx)

    infl.close()

    index = IndexFile(headerlines, files)
    return index
