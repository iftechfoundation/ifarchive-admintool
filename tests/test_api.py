#!/usr/bin/env python3
"""Unit tests for adminlib.api (no Apache required)."""

import hashlib
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tinyapp.util import random_bytes

from adminlib.api import (
    JSONError,
    api_move_file,
    api_update_index,
    authenticate_api_form,
    clean_upload_basename,
    resolve_file_path,
)
from adminlib.hasher import Hasher
from adminlib.index import IndexDir
from adminlib.session import User
from adminlib.util import find_unused_filename as util_find_unused


class FakeApp:
    def __init__(self, root):
        root = os.path.realpath(root)
        self.incoming_dir = os.path.join(root, 'incoming')
        self.trash_dir = os.path.join(root, 'trash')
        self.archive_dir = os.path.join(root, 'archive')
        self.unprocessed_dir = os.path.join(self.archive_dir, 'unprocessed')
        os.makedirs(self.incoming_dir)
        os.makedirs(self.trash_dir)
        os.makedirs(self.unprocessed_dir)
        os.makedirs(os.path.join(self.archive_dir, 'games', 'z-machine'))
        self.db_path = os.path.join(root, 'test.db')
        self._db = sqlite3.connect(self.db_path)
        self._db.isolation_level = None
        curs = self._db.cursor()
        curs.execute(
            'CREATE TABLE users(name unique, email unique, pw, pwsalt, roles, tzname)')
        curs.execute(
            'CREATE TABLE uploads(uploadtime, md5, size, filename, origfilename, '
            'donorname, donoremail, donorip, donoruseragent, permission, '
            'suggestdir, ifdbid, about, usernotes, tuid)')
        self.hasher = Hasher()

    def getdb(self):
        return self._db

    def rewrite_indexdir(self, indexdir):
        from adminlib.util import find_unused_filename
        dirname = indexdir.dirname
        indextext = indexdir.getorigtext()
        if indextext is not None:
            trashname = 'Index-%s' % (dirname.replace('/', '-'),)
            trashname = find_unused_filename(trashname, dir=self.trash_dir)
            trashpath = os.path.join(self.trash_dir, trashname)
            outfl = open(trashpath, 'w', encoding='utf-8')
            outfl.write(indextext)
            outfl.close()
        if not indexdir.hasdata():
            if os.path.exists(indexdir.indexpath):
                os.remove(indexdir.indexpath)
        else:
            indexdir.write()


def add_user(app, name, password, roles, email=None):
    email = email or (name + '@example.com')
    pwsalt = random_bytes(8).encode()
    salted = pwsalt + b':' + password.encode()
    crypted = hashlib.sha1(salted).hexdigest()
    app.getdb().cursor().execute(
        'INSERT INTO users (name, email, pw, pwsalt, roles) VALUES (?, ?, ?, ?, ?)',
        (name, email, crypted, pwsalt, roles))


class FakeReq:
    def __init__(self, app, input=None, user=None):
        self.app = app
        self.input = input or {}
        self.files = {}
        self._user = user

    def get_input_field(self, key, default=None):
        ls = self.input.get(key)
        if ls:
            return ls[0]
        return default


class ResolvePathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = FakeApp(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_incoming_and_archive(self):
        kind, dirname, filename, dirpath = resolve_file_path(
            self.app, 'incoming/foo.zip')
        self.assertEqual(kind, 'incoming')
        self.assertEqual(filename, 'foo.zip')
        self.assertEqual(dirpath, self.app.incoming_dir)

        kind, dirname, filename, dirpath = resolve_file_path(
            self.app, 'games/z-machine/foo.zip')
        self.assertEqual(kind, 'archive')
        self.assertEqual(dirname, 'games/z-machine')
        self.assertEqual(filename, 'foo.zip')

    def test_traversal_rejected(self):
        with self.assertRaises(JSONError) as cm:
            resolve_file_path(self.app, 'games/../../../etc/passwd')
        self.assertTrue(cm.exception.status.startswith('400'))

        with self.assertRaises(JSONError):
            resolve_file_path(self.app, 'incoming/../trash/x')

        with self.assertRaises(JSONError):
            resolve_file_path(self.app, 'no-such-dir/file.zip')

    def test_if_archive_prefix(self):
        kind, dirname, filename, _ = resolve_file_path(
            self.app, 'if-archive/games/z-machine/a.z5')
        self.assertEqual(kind, 'archive')
        self.assertEqual(dirname, 'games/z-machine')
        self.assertEqual(filename, 'a.z5')


class MoveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = FakeApp(self.tmp.name)
        self.incoming_user = User('in', 'in@example.com', roles='incoming')
        self.filing_user = User('fil', 'fil@example.com', roles='filing')
        self.both = User('both', 'both@example.com', roles='incoming,filing')

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, dirpath, name, data=b'x'):
        path = os.path.join(dirpath, name)
        open(path, 'wb').write(data)
        return path

    def test_conflict_409(self):
        self._write(self.app.incoming_dir, 'a.zip')
        dest = os.path.join(self.app.unprocessed_dir, 'a.zip')
        open(dest, 'wb').write(b'old')
        with self.assertRaises(JSONError) as cm:
            api_move_file(
                self.app, self.both,
                'incoming/a.zip', 'unprocessed/a.zip')
        self.assertTrue(cm.exception.status.startswith('409'))

    def test_incoming_cannot_file_to_games(self):
        self._write(self.app.incoming_dir, 'a.zip')
        # First to unprocessed is ok for incoming
        api_move_file(
            self.app, self.incoming_user,
            'incoming/a.zip', 'unprocessed/a.zip')
        with self.assertRaises(JSONError) as cm:
            api_move_file(
                self.app, self.incoming_user,
                'unprocessed/a.zip', 'games/z-machine/a.zip')
        self.assertTrue(cm.exception.status.startswith('403'))

    def test_filing_can_move_to_games(self):
        self._write(self.app.unprocessed_dir, 'a.zip')
        api_move_file(
            self.app, self.filing_user,
            'unprocessed/a.zip', 'games/z-machine/a.zip')
        self.assertTrue(os.path.isfile(
            os.path.join(self.app.archive_dir, 'games', 'z-machine', 'a.zip')))

    def test_move_can_rename(self):
        self._write(self.app.unprocessed_dir, 'old.zip')
        api_move_file(
            self.app, self.filing_user,
            'unprocessed/old.zip', 'games/z-machine/new.zip')
        self.assertFalse(os.path.exists(
            os.path.join(self.app.unprocessed_dir, 'old.zip')))
        self.assertTrue(os.path.isfile(
            os.path.join(self.app.archive_dir, 'games', 'z-machine', 'new.zip')))

    def test_index_moves_with_file(self):
        path = self._write(
            os.path.join(self.app.archive_dir, 'games', 'z-machine'), 'a.zip')
        idx = IndexDir('games/z-machine', rootdir=self.app.archive_dir, orblank=True)
        idx.update('a.zip', 'A game\n', [('tuid', 'abc')])
        idx.write()
        os.makedirs(os.path.join(self.app.archive_dir, 'games', 'other'))
        api_move_file(
            self.app, self.filing_user,
            'games/z-machine/a.zip', 'games/other/a.zip')
        idx2 = IndexDir('games/other', rootdir=self.app.archive_dir, orblank=True)
        self.assertIn('a.zip', idx2.getmap())
        self.assertNotIn('a.zip', [
            f.filename for f in
            IndexDir('games/z-machine', rootdir=self.app.archive_dir, orblank=True).files])


class IndexApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = FakeApp(self.tmp.name)
        open(os.path.join(
            self.app.archive_dir, 'games', 'z-machine', 'a.zip'), 'wb').write(b'x')

    def tearDown(self):
        self.tmp.cleanup()

    def test_update_file_and_directory(self):
        result = api_update_index(
            self.app, 'games/z-machine', 'a.zip',
            description='Hello', metadata='tuid: deadbeef\n',
            have_description=True, have_metadata=True)
        self.assertEqual(result['filename'], 'a.zip')
        self.assertIn('Hello', result['description'])
        self.assertIn('tuid:', result['metadata'])

        result = api_update_index(
            self.app, 'games/z-machine', '.',
            description='Dir desc', metadata='',
            have_description=True, have_metadata=True)
        self.assertEqual(result['filename'], '.')
        self.assertIn('Dir desc', result['description'])

    def test_partial_update_and_bad_meta(self):
        api_update_index(
            self.app, 'games/z-machine', 'a.zip',
            description='One', metadata='tuid: aaa\n',
            have_description=True, have_metadata=True)
        api_update_index(
            self.app, 'games/z-machine', 'a.zip',
            description='Two',
            have_description=True, have_metadata=False)
        idx = IndexDir('games/z-machine', rootdir=self.app.archive_dir)
        ent = idx.getmap()['a.zip']
        self.assertIn('Two', ent.description)
        self.assertEqual(ent.metadata[0][0], 'tuid')

        with self.assertRaises(JSONError) as cm:
            api_update_index(
                self.app, 'games/z-machine', 'a.zip',
                metadata='not metadata at all',
                have_description=False, have_metadata=True)
        self.assertTrue(cm.exception.status.startswith('400'))


class AuthAndUploadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = FakeApp(self.tmp.name)
        add_user(self.app, 'alice', 'secret', 'incoming,index,filing')

    def tearDown(self):
        self.tmp.cleanup()

    def test_auth_requires_password_not_session(self):
        # Session user present but no form password
        req = FakeReq(self.app, input={}, user=User('alice', 'a@x.com', roles='admin'))
        with self.assertRaises(JSONError) as cm:
            authenticate_api_form(req)
        self.assertTrue(cm.exception.status.startswith('401'))
        self.assertIsNone(req._user)

        req = FakeReq(self.app, input={
            'user': ['alice'], 'password': ['wrong']})
        with self.assertRaises(JSONError):
            authenticate_api_form(req)

        req = FakeReq(self.app, input={
            'user': ['alice'], 'password': ['secret']})
        authenticate_api_form(req)
        self.assertEqual(req._user.name, 'alice')

    def test_upload_renames(self):
        open(os.path.join(self.app.incoming_dir, 'f.zip'), 'wb').write(b'a')
        name = util_find_unused('f.zip', self.app.incoming_dir)
        self.assertEqual(name, 'f.zip.1')
        open(os.path.join(self.app.incoming_dir, name), 'wb').write(b'b')
        name2 = util_find_unused('f.zip', self.app.incoming_dir)
        self.assertEqual(name2, 'f.zip.2')

    def test_clean_basename(self):
        self.assertEqual(clean_upload_basename('dir/x.zip'), 'x.zip')
        with self.assertRaises(JSONError):
            clean_upload_basename('.')
        with self.assertRaises(JSONError):
            clean_upload_basename('Index')


if __name__ == '__main__':
    unittest.main()
