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
    def __init__(self, dirname, rootdir=None):
        self.dirname = dirname
        self.indexpath = os.path.join(rootdir, dirname, 'Index')

        self.description = []
        self.metadata = OrderedDict()
        self.files = []
        self.filemap = OrderedDict()

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
                self.filemap[filename] = curfile
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
                        self.add_metadata(curmetaline, val, dirty=False)
                        continue
                    elif type(curmetaline) is str and match2:
                        val = ln[match2.end() : ].strip()
                        self.add_metadata(curmetaline, val, dirty=False)
                        continue
                    else:
                        curmetaline = None
                # We're done with the directory metadata, so this is a directory description line.
                # For consistency, the description will always start with a blank line.
                if len(self.description) == 0 and ln.strip() != '':
                    self.description.append('\n')
                self.description.append(ln)
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
                    curfile.add_metadata(curmetaline, val, dirty=False)
                    continue
                elif type(curmetaline) is str and match2:
                    val = ln[match2.end() : ].strip()
                    curfile.add_metadata(curmetaline, val, dirty=False)
                    continue
                else:
                    curmetaline = None
                # We're done with the metadata, so this is a description line.

            # For consistency, the description will always start with a blank line.
            if len(curfile.description) == 0 and ln.strip() != '':
                curfile.description.append('\n')
                
            curfile.description.append(ln)
            
                
        infl.close()

    def __repr__(self):
        return '<IndexDir %s>' % (self.dirname,)

    def add_metadata(self, key, val, dirty=True):
        ls = self.metadata.get(key)
        if ls is None:
            ls = []
            self.metadata[key] = ls
        ls.append(val)
        if dirty:
            self.dirty = True


class IndexFile:
    def __init__(self, filename, dir):
        self.filename = filename
        self.dir = dir
        self.description = []
        self.metadata = OrderedDict()
        self.dirty = False
        
    def __repr__(self):
        return '<IndexFile %s>' % (self.filename,)

    def add_metadata(self, key, val, dirty=True):
        ls = self.metadata.get(key)
        if ls is None:
            ls = []
            self.metadata[key] = ls
        ls.append(val)
        if dirty:
            self.dirty = True
