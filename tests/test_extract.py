#!/usr/bin/env python3
"""Unit tests for adminlib.extract (no Apache required)."""

import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adminlib.extract import (
    ExtractError,
    list_zip_members,
    common_toplevel,
    plan_extract_paths,
    find_conflicts,
    check_unprocessed_extract,
    ensure_archive_dest,
    perform_extract,
    find_zip_member,
    iter_zip_member_bytes,
)


def write_zip(path, entries):
    """entries: list of (name, bytes|None). None => directory."""
    with zipfile.ZipFile(path, 'w') as zf:
        for name, data in entries:
            if data is None:
                zf.writestr(name if name.endswith('/') else name + '/', b'')
            else:
                zf.writestr(name, data)


class ExtractTests(unittest.TestCase):
    def test_list_and_toplevel(self):
        with tempfile.TemporaryDirectory() as tmp:
            zpath = os.path.join(tmp, 't.zip')
            write_zip(zpath, [
                ('bundle/a.txt', b'a'),
                ('bundle/sub/b.txt', b'bb'),
                ('bundle/', None),
            ])
            members = list_zip_members(zpath)
            self.assertEqual(common_toplevel(members), 'bundle')

    def test_zip_slip_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            zpath = os.path.join(tmp, 't.zip')
            write_zip(zpath, [('../evil.txt', b'x')])
            with self.assertRaises(ExtractError):
                list_zip_members(zpath)

    def test_preserve_and_strip(self):
        with tempfile.TemporaryDirectory() as tmp:
            zpath = os.path.join(tmp, 't.zip')
            write_zip(zpath, [
                ('bundle/a.txt', b'a'),
                ('bundle/sub/b.txt', b'bb'),
            ])
            members = list_zip_members(zpath)
            planned = plan_extract_paths(members, pathmode='preserve', strip=True)
            rels = sorted(p.relpath for p in planned if not p.member.is_dir)
            self.assertEqual(rels, ['a.txt', 'sub/b.txt'])

    def test_flat_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            zpath = os.path.join(tmp, 't.zip')
            write_zip(zpath, [
                ('one/a.txt', b'a'),
                ('two/a.txt', b'b'),
            ])
            members = list_zip_members(zpath)
            with self.assertRaises(ExtractError):
                plan_extract_paths(members, pathmode='flat')

    def test_conflicts_and_extract(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, 'archive')
            os.makedirs(os.path.join(archive, 'unprocessed'))
            zpath = os.path.join(tmp, 't.zip')
            write_zip(zpath, [
                ('Games/x.zip', b'zzz'),
                ('README.txt', b'hi'),
            ])
            members = list_zip_members(zpath)
            planned = plan_extract_paths(members, pathmode='preserve')
            dest = ensure_archive_dest('games/competition2025', archive, create=True)
            abs_dest = os.path.join(archive, *dest.split('/'))
            self.assertEqual(find_conflicts(abs_dest, planned), [])
            n = perform_extract(zpath, abs_dest, planned)
            self.assertEqual(n, 2)
            self.assertTrue(os.path.isfile(os.path.join(abs_dest, 'Games', 'x.zip')))
            # Parent zip untouched
            self.assertTrue(os.path.isfile(zpath))
            # Conflict on re-extract
            conflicts = find_conflicts(abs_dest, planned)
            self.assertEqual(len(conflicts), 2)

    def test_refuse_archive_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, 'archive')
            os.makedirs(archive)
            with self.assertRaises(ExtractError):
                ensure_archive_dest('', archive, create=True)

    def test_refuse_subdirs_into_unprocessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            zpath = os.path.join(tmp, 't.zip')
            write_zip(zpath, [
                ('Games/x.zip', b'zzz'),
                ('README.txt', b'hi'),
            ])
            members = list_zip_members(zpath)
            planned = plan_extract_paths(members, pathmode='preserve')
            with self.assertRaises(ExtractError) as cm:
                check_unprocessed_extract('unprocessed', planned)
            self.assertIn('unprocessed', str(cm.exception).lower())

            flat = plan_extract_paths(members, pathmode='flat')
            check_unprocessed_extract('unprocessed', flat)  # ok: top-level only
            check_unprocessed_extract('games/competition2025', planned)  # ok: not unprocessed

    def test_find_and_read_zip_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            zpath = os.path.join(tmp, 't.zip')
            write_zip(zpath, [
                ('Games/x.zip', b'zzz'),
                ('README.txt', b'hi'),
            ])
            members = list_zip_members(zpath)
            mem = find_zip_member(members, 'Games/x.zip')
            self.assertEqual(mem.name, 'Games/x.zip')
            self.assertEqual(b''.join(iter_zip_member_bytes(zpath, mem.raw_name)), b'zzz')
            with self.assertRaises(ExtractError):
                find_zip_member(members, 'nope.txt')
            with self.assertRaises(ExtractError):
                find_zip_member(members, '../evil.txt')


if __name__ == '__main__':
    unittest.main()
