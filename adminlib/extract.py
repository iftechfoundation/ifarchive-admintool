"""Helpers for extracting zip archives into the IF Archive tree.
"""

from __future__ import annotations

import os
import os.path
import shutil
import zipfile
from dataclasses import dataclass

# Avoid importing adminlib.util (pulls in pytz) so helpers stay lightweight.


def bad_filename(val):
    """Same rules as adminlib.util.bad_filename."""
    if not val:
        return True
    if '/' in val:
        return True
    if '\x00' in val:
        return True
    if val == '.' or val == '..':
        return True
    return False


# Require this much free space beyond the zip's reported uncompressed size.
DISK_MARGIN_BYTES = 10 * 1000 * 1000


class ExtractError(Exception):
    """User-facing extract/planning error."""
    pass


@dataclass
class ZipMember:
    """One entry from a zip's central directory."""
    name: str          # normalized relative path using '/'
    size: int          # uncompressed size (0 for directories)
    is_dir: bool
    raw_name: str      # original ZipInfo.filename


@dataclass
class PlannedPath:
    """One planned output file or directory."""
    member: ZipMember
    relpath: str       # relative to destination dir, using '/'


def is_zip_filename(filename: str) -> bool:
    return filename.lower().endswith('.zip')


def _normalize_member_name(raw: str) -> str:
    """Return a safe relative path using '/', or raise ExtractError."""
    if not raw or raw.endswith('\x00') or '\x00' in raw:
        raise ExtractError('Zip contains an invalid member name.')
    # Zip paths use '/'; also tolerate '\'
    name = raw.replace('\\', '/')
    if name.startswith('/') or (len(name) >= 2 and name[1] == ':'):
        raise ExtractError('Zip contains an absolute path: %s' % (raw,))
    parts = [p for p in name.split('/') if p not in ('', '.')]
    if any(p == '..' for p in parts):
        raise ExtractError('Zip contains a path with "..": %s' % (raw,))
    if any(bad_filename(p) for p in parts):
        # bad_filename rejects empty, '.', '..', '/', NUL — already handled
        # mostly; also reject oddities consistently.
        raise ExtractError('Zip contains an invalid path segment: %s' % (raw,))
    return '/'.join(parts)


def list_zip_members(zippath: str) -> list[ZipMember]:
    """List file/dir members of a zip. Raises ExtractError on bad members."""
    try:
        zf = zipfile.ZipFile(zippath, mode='r')
    except zipfile.BadZipFile as ex:
        raise ExtractError('Not a valid zip file: %s' % (ex,)) from ex
    try:
        members = []
        for info in zf.infolist():
            raw = info.filename
            is_dir = raw.endswith('/') or info.is_dir()
            try:
                name = _normalize_member_name(raw)
            except ExtractError:
                raise
            if not name:
                # Root-only entry; ignore.
                continue
            members.append(ZipMember(
                name=name,
                size=0 if is_dir else info.file_size,
                is_dir=is_dir,
                raw_name=raw,
            ))
        return members
    finally:
        zf.close()


def find_zip_member(members: list[ZipMember], member_name: str) -> ZipMember:
    """Look up a non-directory member by normalized path. Raises ExtractError."""
    if not member_name:
        raise ExtractError('Missing zip member name.')
    try:
        name = _normalize_member_name(member_name)
    except ExtractError:
        raise ExtractError('Invalid zip member name.') from None
    for mem in members:
        if mem.name == name:
            if mem.is_dir:
                raise ExtractError('Not a file in the zip: %s' % (name,))
            return mem
    raise ExtractError('Not found in zip: %s' % (name,))


def iter_zip_member_bytes(zippath: str, raw_name: str, chunk_size: int = 8192):
    """Yield bytes from one zip member. Closes the zip when iteration ends."""
    zf = zipfile.ZipFile(zippath, mode='r')
    try:
        src = zf.open(raw_name)
    except Exception:
        zf.close()
        raise
    try:
        while True:
            chunk = src.read(chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        src.close()
        zf.close()


def common_toplevel(members: list[ZipMember]) -> str | None:
    """If every member lives under one shared top-level folder, return it.

    The top-level name itself may appear as a directory entry. Returns None
    if there is no single shared prefix (or only one file at the root).
    """
    if not members:
        return None
    tops = set()
    for mem in members:
        parts = mem.name.split('/')
        tops.add(parts[0])
    if len(tops) != 1:
        return None
    top = next(iter(tops))
    # Require that at least one member is under top/ (not only top itself),
    # otherwise stripping does nothing useful for a single root file.
    has_nested = any('/' in mem.name for mem in members)
    if not has_nested:
        return None
    return top


def plan_extract_paths(
    members: list[ZipMember],
    pathmode: str = 'preserve',
    strip: bool = False,
    strip_prefix: str | None = None,
) -> list[PlannedPath]:
    """Compute output relative paths for each member.

    pathmode: 'preserve' or 'flat'
    strip: if True, remove strip_prefix (or auto common_toplevel) from paths.
    """
    if pathmode not in ('preserve', 'flat'):
        raise ExtractError('Invalid path mode: %s' % (pathmode,))

    prefix = None
    if strip:
        prefix = strip_prefix or common_toplevel(members)
        if not prefix:
            raise ExtractError(
                'Cannot strip top-level folder: zip contents do not share one.'
            )

    planned: list[PlannedPath] = []
    seen_files: dict[str, str] = {}  # relpath -> source member name

    for mem in members:
        rel = mem.name
        if prefix:
            if rel == prefix:
                # The directory entry for the stripped folder itself.
                continue
            lead = prefix + '/'
            if not rel.startswith(lead):
                raise ExtractError(
                    'Member is outside the strip prefix "%s": %s'
                    % (prefix, mem.name,)
                )
            rel = rel[len(lead):]
            if not rel:
                continue

        if pathmode == 'flat':
            if mem.is_dir:
                # Flat mode only materializes files; dirs are implied.
                continue
            rel = rel.split('/')[-1]
            if not rel:
                continue

        if mem.is_dir:
            # Directory-only entries: keep for preserve mode so empty dirs
            # can be created; skip if somehow empty.
            if not rel:
                continue
            planned.append(PlannedPath(member=mem, relpath=rel))
            continue

        if rel in seen_files:
            raise ExtractError(
                'Planned output collision: "%s" from both "%s" and "%s"'
                % (rel, seen_files[rel], mem.name,)
            )
        seen_files[rel] = mem.name
        planned.append(PlannedPath(member=mem, relpath=rel))

    return planned


def uncompressed_bytes(members: list[ZipMember]) -> int:
    return sum(m.size for m in members if not m.is_dir)


def check_disk_space(dest_root: str, need_bytes: int) -> None:
    """Raise ExtractError if dest filesystem lacks space for need_bytes + margin."""
    usage = shutil.disk_usage(dest_root if os.path.exists(dest_root) else os.path.dirname(dest_root) or dest_root)
    required = need_bytes + DISK_MARGIN_BYTES
    if usage.free < required:
        raise ExtractError(
            'Not enough free disk space: need about %s bytes free, have %s'
            % (required, usage.free,)
        )


def find_conflicts(dest_dir: str, planned: list[PlannedPath]) -> list[str]:
    """Return list of relative paths that would conflict with existing files."""
    conflicts = []
    for item in planned:
        abs_path = os.path.join(dest_dir, *item.relpath.split('/'))
        if item.member.is_dir:
            if os.path.isfile(abs_path) or os.path.islink(abs_path):
                conflicts.append(item.relpath)
            continue
        # File: conflict if anything exists at path, or a path component is a file
        if os.path.exists(abs_path) or os.path.lexists(abs_path):
            conflicts.append(item.relpath)
            continue
        # Walk parents: if a parent exists as a file, conflict
        parent = os.path.dirname(abs_path)
        while parent and parent.startswith(dest_dir):
            if os.path.isfile(parent) or os.path.islink(parent):
                conflicts.append(item.relpath)
                break
            if parent == dest_dir:
                break
            parent = os.path.dirname(parent)
    return conflicts


def check_unprocessed_extract(dest_rel: str, planned: list[PlannedPath]) -> None:
    """Refuse nested layouts into /unprocessed (flat file staging only)."""
    if dest_rel != 'unprocessed':
        return
    for item in planned:
        if item.member.is_dir or '/' in item.relpath:
            raise ExtractError(
                'You cannot extract subdirectories into /unprocessed. '
                'Choose an Archive directory, or use flat layout so every file '
                'lands at the top level of /unprocessed.'
            )


def ensure_archive_dest(dirname: str, archivedir: str, create: bool = False) -> str:
    """Validate (and optionally create) an Archive-relative directory.

    Returns the canonical relative path (no leading slash). Raises
    ExtractError on problems. Refuses Archive root.
    """
    if dirname is None:
        raise ExtractError('Directory not found.')
    val = dirname.strip()
    if val.startswith('/'):
        val = val[1:]
    if val.startswith('if-archive/'):
        val = val[11:]
    if val.endswith('/'):
        val = val[:-1]
    if not val or val == '.':
        raise ExtractError('You cannot extract files to the Archive root.')

    parts = [p for p in val.split('/') if p]
    if not parts:
        raise ExtractError('You cannot extract files to the Archive root.')
    for part in parts:
        if bad_filename(part):
            raise ExtractError('Invalid directory path: %s' % (dirname,))

    pathname = os.path.join(archivedir, *parts)
    abs_archive = os.path.realpath(archivedir)
    if create:
        os.makedirs(pathname, exist_ok=True)

    try:
        pathname = os.path.realpath(pathname)
        if not os.path.exists(pathname):
            raise Exception('dir not found')
    except Exception as ex:
        raise ExtractError('Directory not found: %s' % (dirname,)) from ex

    if not pathname.startswith(abs_archive + os.sep) and pathname != abs_archive:
        raise ExtractError('Not an Archive directory: %s' % (dirname,))
    if pathname == abs_archive:
        raise ExtractError('You cannot extract files to the Archive root.')
    if (not os.path.isdir(pathname)) or os.path.islink(pathname):
        raise ExtractError('Not a directory: %s' % (dirname,))

    rel = pathname[len(abs_archive):]
    if rel.startswith(os.sep):
        rel = rel[1:]
    return rel.replace(os.sep, '/')


def perform_extract(zippath: str, dest_dir: str, planned: list[PlannedPath]) -> int:
    """Extract planned members into dest_dir. Returns number of files written.

    Never overwrites. Parent zip is left untouched. Raises ExtractError.
    """
    # Re-check conflicts immediately before writing.
    conflicts = find_conflicts(dest_dir, planned)
    if conflicts:
        raise ExtractError(
            'Conflicts with existing files: %s'
            % (', '.join(conflicts[:20]) + ('…' if len(conflicts) > 20 else ''),)
        )

    files_written = 0
    try:
        zf = zipfile.ZipFile(zippath, mode='r')
    except zipfile.BadZipFile as ex:
        raise ExtractError('Not a valid zip file: %s' % (ex,)) from ex

    try:
        for item in planned:
            abs_path = os.path.join(dest_dir, *item.relpath.split('/'))
            if item.member.is_dir:
                os.makedirs(abs_path, exist_ok=True)
                continue
            parent = os.path.dirname(abs_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            if os.path.exists(abs_path) or os.path.lexists(abs_path):
                raise ExtractError('Refusing to overwrite: %s' % (item.relpath,))
            with zf.open(item.member.raw_name) as src:
                # Exclusive create
                fd = os.open(abs_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
                try:
                    with os.fdopen(fd, 'wb') as out:
                        shutil.copyfileobj(src, out)
                except Exception:
                    try:
                        os.remove(abs_path)
                    except OSError:
                        pass
                    raise
            files_written += 1
    finally:
        zf.close()

    return files_written
