"""JSON form APIs for bulk volunteer work (upload, move, Index).

Authentication is username+password form fields on every request.
Session cookies are ignored. See API.md.
"""

import hashlib
import json
import os
import os.path
import re
import shutil

from tinyapp.constants import JSON
from tinyapp.excepts import HTTPError
from tinyapp.handler import ReqHandler
from tinyapp.util import time_now

from adminlib.index import IndexDir
from adminlib.info import FileEntry
from adminlib.session import User
from adminlib.util import (
    FileConsistency,
    bad_filename,
    canon_archivedir,
    clean_newlines,
    find_unused_filename,
)


class JSONError(HTTPError):
    """HTTP error with a JSON {"error": ...} body."""

    def do_error(self, req):
        req.set_content_type(JSON)
        yield json.dumps({'error': self.msg})


def json_response(req, data, status='200 OK'):
    """Yield a JSON response body."""
    req.set_status(status)
    req.set_content_type(JSON)
    yield json.dumps(data)


def authenticate_api_form(req):
    """Authenticate from form fields user+password only.

    Clears any session-derived req._user so cookie login cannot authorize
    the API.
    """
    req._user = None
    formname = req.get_input_field('user')
    formpw = req.get_input_field('password')
    if not (formname and formpw):
        raise JSONError('401 Unauthorized', 'Missing user or password')

    curs = req.app.getdb().cursor()
    if '@' in formname:
        res = curs.execute(
            'SELECT name, email, pw, pwsalt, roles, tzname FROM users WHERE email = ?',
            (formname,))
    else:
        res = curs.execute(
            'SELECT name, email, pw, pwsalt, roles, tzname FROM users WHERE name = ?',
            (formname,))
    tup = res.fetchone()
    if not tup:
        raise JSONError('401 Unauthorized', 'Invalid user or password')

    name, email, pw, pwsalt, roles, tzname = tup
    formsalted = pwsalt + b':' + formpw.encode()
    formcrypted = hashlib.sha1(formsalted).hexdigest()
    if formcrypted != pw:
        raise JSONError('401 Unauthorized', 'Invalid user or password')

    req._user = User(name, email, roles=roles, tzname=tzname)


def require_api_role(req, *roles):
    """Ensure req._user has one of the given roles."""
    if not req._user:
        raise JSONError('401 Unauthorized', 'Not logged in')
    for role in roles:
        if role in req._user.roles:
            return
    raise JSONError('403 Forbidden', 'Not authorized for this operation')


def format_metadata(pairs):
    """Format Index metadata key/value pairs as form-style text."""
    if not pairs:
        return ''
    lines = ['%s: %s' % (key, val) for key, val in pairs]
    return '\n'.join(lines) + '\n'


def clean_upload_basename(fn):
    """Strip directory parts and validate an upload basename."""
    if not fn:
        fn = 'file'
    _, _, fn = fn.rpartition('/')
    _, _, fn = fn.rpartition('\\')
    if not fn:
        fn = 'file'
    if bad_filename(fn) or fn in FileEntry.specialnames:
        raise JSONError('400 Bad Request', 'Invalid filename: %s' % (fn,))
    return fn


# Path like incoming/foo.zip or games/z-machine/foo.zip
_path_sep = re.compile(r'/+')


def resolve_file_path(app, path):
    """Resolve an API file path to (kind, dirname, filename, dirpath).

    kind is 'incoming', 'trash', or 'archive'.
    dirname is the archive-relative directory ('' for root) or None for
    incoming/trash.
    Raises JSONError on invalid paths.
    """
    if path is None or not str(path).strip():
        raise JSONError('400 Bad Request', 'Missing path')
    path = str(path).strip()
    if path.startswith('/'):
        path = path[1:]
    if path.startswith('if-archive/'):
        path = path[11:]
    if not path or path in ('.', '..') or '\\' in path or '\x00' in path:
        raise JSONError('400 Bad Request', 'Invalid path: %s' % (path,))
    # Reject empty segments and .. after split
    parts = [p for p in _path_sep.split(path) if p]
    if not parts or any(p in ('.', '..') for p in parts):
        raise JSONError('400 Bad Request', 'Invalid path: %s' % (path,))

    if parts[0] == 'incoming':
        if len(parts) != 2:
            raise JSONError('400 Bad Request', 'Invalid incoming path: %s' % (path,))
        filename = parts[1]
        if bad_filename(filename):
            raise JSONError('400 Bad Request', 'Invalid filename: %s' % (filename,))
        return ('incoming', None, filename, app.incoming_dir)

    if parts[0] == 'trash':
        if len(parts) != 2:
            raise JSONError('400 Bad Request', 'Invalid trash path: %s' % (path,))
        filename = parts[1]
        if bad_filename(filename):
            raise JSONError('400 Bad Request', 'Invalid filename: %s' % (filename,))
        return ('trash', None, filename, app.trash_dir)

    # Archive path: last component is filename, rest is directory
    if len(parts) < 2:
        raise JSONError(
            '400 Bad Request',
            'Archive path must include a directory and filename: %s' % (path,))
    filename = parts[-1]
    if bad_filename(filename) or filename in FileEntry.specialnames:
        raise JSONError('400 Bad Request', 'Invalid filename: %s' % (filename,))
    dirname = '/'.join(parts[:-1])
    try:
        dirname = canon_archivedir(dirname, archivedir=app.archive_dir)
    except FileConsistency:
        raise JSONError('400 Bad Request', 'Not an Archive directory: %s' % (dirname,))
    if not dirname:
        # File in archive root — UI does not allow move from/to root for files
        # via free-text to root; still resolve for Index of files in root? 
        # Move policy forbids archive root as dest; source from root also
        # has no move in UI. Allow resolve but callers check policy.
        pass
    dirpath = os.path.join(app.archive_dir, dirname) if dirname else app.archive_dir
    return ('archive', dirname, filename, dirpath)


def can_move_from(user, kind, dirname):
    """Whether user may move a file from this location (mirrors get_fileops)."""
    if kind == 'incoming':
        return user.has_role('incoming')
    if kind == 'trash':
        return user.has_role('incoming')
    # archive
    if dirname == 'unprocessed':
        return user.has_role('incoming', 'filing')
    if not dirname:
        return False  # archive root: no move in UI
    return user.has_role('filing')


def can_move_to(user, kind, dirname):
    """Whether user may move a file to this location."""
    if kind == 'incoming':
        return user.has_role('incoming')
    if kind == 'trash':
        return False
    if not dirname:
        return False  # archive root forbidden
    if dirname == 'unprocessed':
        return user.has_role('incoming', 'filing')
    return user.has_role('filing')


def api_move_file(app, user, from_path, to_path):
    """Move a file (optionally renaming). Returns (from_canon, to_canon).

    Raises JSONError.
    """
    skind, sdirname, sfilename, sdirpath = resolve_file_path(app, from_path)
    dkind, ddirname, dfilename, ddirpath = resolve_file_path(app, to_path)

    if not can_move_from(user, skind, sdirname):
        raise JSONError('403 Forbidden', 'Not allowed to move from %s' % (from_path,))
    if not can_move_to(user, dkind, ddirname):
        raise JSONError('403 Forbidden', 'Not allowed to move to %s' % (to_path,))

    if skind == dkind and sdirname == ddirname and sfilename == dfilename:
        raise JSONError('400 Bad Request', 'Source and destination are the same')

    src = os.path.join(sdirpath, sfilename)
    dst = os.path.join(ddirpath, dfilename)

    if not os.path.isfile(src) or os.path.islink(src):
        raise JSONError('404 Not Found', 'Source file not found: %s' % (from_path,))
    if os.path.exists(dst):
        raise JSONError(
            '409 Conflict',
            'A file named %s already exists at destination' % (dfilename,))

    shutil.move(src, dst)

    # Index entry transfer / rename (archive → archive, not to unprocessed)
    if skind == 'archive' and dkind == 'archive' and ddirname != 'unprocessed':
        indexdir = IndexDir(sdirname, rootdir=app.archive_dir, orblank=True)
        ient = indexdir.getmap().get(sfilename)
        if ient and ient.filename != '.':
            if sdirname == ddirname:
                ient.filename = dfilename
                app.rewrite_indexdir(indexdir)
            else:
                indexdir2 = IndexDir(ddirname, rootdir=app.archive_dir, orblank=True)
                moved = ient.copy()
                moved.filename = dfilename
                indexdir2.add(moved)
                indexdir.delete(sfilename)
                app.rewrite_indexdir(indexdir2)
                app.rewrite_indexdir(indexdir)

    from_canon = _canon_label(skind, sdirname, sfilename)
    to_canon = _canon_label(dkind, ddirname, dfilename)
    return from_canon, to_canon


def _canon_label(kind, dirname, filename):
    if kind == 'incoming':
        return 'incoming/' + filename
    if kind == 'trash':
        return 'trash/' + filename
    if dirname:
        return dirname + '/' + filename
    return filename


def api_update_index(app, dirname, filename, description=None, metadata=None,
                     have_description=False, have_metadata=False):
    """Update one Index entry. Returns result dict. Raises JSONError."""
    if filename != '.' and bad_filename(filename):
        raise JSONError('400 Bad Request', 'Invalid filename: %s' % (filename,))
    if filename != '.' and filename in FileEntry.specialnames:
        raise JSONError('400 Bad Request', 'Invalid filename: %s' % (filename,))

    if dirname is None:
        dirname = ''
    dirname = str(dirname).strip()
    if dirname.startswith('/'):
        dirname = dirname[1:]
    if dirname.startswith('if-archive/'):
        dirname = dirname[11:]
    try:
        dirname = canon_archivedir(dirname, archivedir=app.archive_dir)
    except FileConsistency:
        raise JSONError('400 Bad Request', 'Not an Archive directory: %s' % (dirname,))

    if not have_description and not have_metadata:
        raise JSONError(
            '400 Bad Request',
            'Must supply description and/or metadata')

    indexdir = IndexDir(dirname, rootdir=app.archive_dir, orblank=True)
    amap = indexdir.getmap()
    old = amap.get(filename)

    if have_description:
        newdesc = clean_newlines(description or '', prestrip=True)
    else:
        newdesc = (old.description if old and old.description else '') or ''

    if have_metadata:
        meta_text = metadata or ''
        try:
            newmetalines = IndexDir.check_metablock(meta_text)
        except Exception as ex:
            raise JSONError('400 Bad Request', 'Metadata error: %s' % (ex,))
    else:
        newmetalines = list(old.metadata) if old else []

    indexdir.update(filename, newdesc, newmetalines)
    app.rewrite_indexdir(indexdir)

    # Re-read for response
    indexdir = IndexDir(dirname, rootdir=app.archive_dir, orblank=True)
    ent = indexdir.getmap().get(filename)
    desc_out = ''
    meta_out = ''
    if ent:
        if ent.description:
            desc_out = ent.description.strip()
        meta_out = format_metadata(ent.metadata)
    return {
        'dirname': dirname,
        'filename': filename,
        'description': desc_out,
        'metadata': meta_out,
    }


class han_ApiUpload(ReqHandler):
    def do_post(self, req):
        authenticate_api_form(req)
        require_api_role(req, 'incoming')

        rights = req.get_input_field('rights')
        if rights not in ('author', 'tried'):
            raise JSONError(
                '400 Bad Request',
                'Missing or invalid rights (must be author or tried)')

        fileinfo = req.get_input_file('file')
        if not fileinfo:
            raise JSONError('400 Bad Request', 'Missing file')
        client_name, content = fileinfo
        override = req.get_input_field('filename')
        if override:
            basename = clean_upload_basename(override)
        else:
            basename = clean_upload_basename(client_name)

        finalname = find_unused_filename(basename, self.app.incoming_dir)
        destpath = os.path.join(self.app.incoming_dir, finalname)
        outfl = open(destpath, 'wb')
        outfl.write(content)
        outfl.close()

        md5, size = self.app.hasher.get_md5_size(destpath)
        now = time_now()
        curs = self.app.getdb().cursor()
        curs.execute(
            'INSERT INTO uploads (uploadtime, md5, size, filename, origfilename, '
            'donorname, donoremail, permission) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (now, md5, size, finalname, client_name or basename,
             req._user.name, req._user.email, rights))

        req.loginfo('API upload "%s" (md5 %s)', finalname, md5)
        return json_response(req, {'filename': finalname, 'md5': md5})


class han_ApiMove(ReqHandler):
    def do_post(self, req):
        authenticate_api_form(req)
        # Role checked inside api_move_file based on paths
        if not req._user:
            raise JSONError('401 Unauthorized', 'Not logged in')

        from_path = req.get_input_field('from')
        to_path = req.get_input_field('to')
        if not from_path or not to_path:
            raise JSONError('400 Bad Request', 'Missing from or to')

        from_canon, to_canon = api_move_file(
            self.app, req._user, from_path, to_path)
        req.loginfo('API move "%s" to "%s"', from_canon, to_canon)
        return json_response(req, {'from': from_canon, 'to': to_canon})


class han_ApiIndex(ReqHandler):
    def do_post(self, req):
        authenticate_api_form(req)
        require_api_role(req, 'index')

        dirname = req.get_input_field('dirname', '')
        filename = req.get_input_field('filename')
        if filename is None or filename == '':
            raise JSONError('400 Bad Request', 'Missing filename')

        have_description = 'description' in req.input
        have_metadata = 'metadata' in req.input
        description = req.get_input_field('description') if have_description else None
        metadata = req.get_input_field('metadata') if have_metadata else None

        result = api_update_index(
            self.app, dirname, filename,
            description=description, metadata=metadata,
            have_description=have_description, have_metadata=have_metadata)
        req.loginfo(
            'API index update "%s" in /%s',
            filename, dirname or '')
        return json_response(req, result)
