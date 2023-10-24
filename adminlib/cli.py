import argparse
import os, os.path
import time
import hashlib
import logging

from tinyapp.util import random_bytes, time_now
from adminlib.util import read_md5, read_size

def run(appinstance):
    """The entry point when admin.wsgi is invoked on the command line.
    """
    popt = argparse.ArgumentParser(prog='admin.wsgi')
    ### cleanup | adduser | userroles | userpw | createdb | addupload | test
    subopt = popt.add_subparsers(dest='cmd', title='commands')

    popt_cleanup = subopt.add_parser('cleanup', help='clean out trash, etc')
    
    popt_adduser = subopt.add_parser('adduser', help='add a user')
    
    popt_userroles = subopt.add_parser('userroles', help='change a user\'s roles')
    
    popt_userpw = subopt.add_parser('userpw', help='change a user\'s password')
    
    popt_createdb = subopt.add_parser('createdb', help='create database tables')
    
    popt_addupload = subopt.add_parser('addupload', help='add a file to the upload log')
    
    popt_test = subopt.add_parser('test', help='print page to stdout')
    popt_test.add_argument('uri', nargs='?', metavar='URI')
    
    args = popt.parse_args()
    print('###', args)

    if True:
        popt.print_help()
        return
    
    cmd = args.pop(0)
    
    if cmd == 'test':
        uri = ''
        if args:
            uri = args[0]
        appinstance.test_dump(uri)
    elif cmd == 'cleanup':
        db_cleanup(appinstance, appinstance.getdb())
    elif cmd == 'createdb':
        db_create(appinstance.getdb())
    elif cmd == 'adduser':
        db_add_user(appinstance.getdb(), args)
    elif cmd == 'userroles':
        db_user_roles(appinstance.getdb(), args)
    elif cmd == 'userpw':
        db_user_pw(appinstance.getdb(), args)
    elif cmd == 'addupload':
        db_add_upload(appinstance.getdb(), args)
    else:
        print('command not recognized: %s' % (cmd,))
        print('Usage: %s' % (popt.usage,))

def get_curuser():
    """getlogin() fails sometimes, I dunno why. So we catch exceptions.
    """
    try:
        return os.getlogin()
    except:
        return '???'
        

def db_cleanup(app, db):
    """Clean up stuff that needs to be cleaned up periodically.
    Should be run from a cron job.
    """
    logging.info('CLI user=%s: cleanup', get_curuser())

    # Clean out old sessions. Note that in the sessions table
    # (refreshtime >= starttime), so we just look at refreshtime.
    timelimit = time.time() - app.max_session_age
    curs = db.cursor()
    res = curs.execute('DELETE FROM sessions WHERE refreshtime < ?', (timelimit,))

    # Clean out old trash files.
    timelimit = time.time() - app.max_trash_age
    dells = []
    for ent in os.scandir(app.trash_dir):
        if ent.is_file():
            stat = ent.stat()
            if stat.st_mtime < timelimit:
                dells.append(ent.name)

    for name in dells:
        print('Deleting "%s" from trash...' % (name,))
        pathname = os.path.join(app.trash_dir, name)
        os.remove(pathname)

def db_create(db):
    """Create the database tables. This only needs to be done once ever,
    unless of course we change the table structure or decide to wipe
    and start over.
    """
    logging.info('CLI user=%s: createdb', get_curuser())
    curs = db.cursor()
    res = curs.execute('SELECT name FROM sqlite_master')
    tables = [ tup[0] for tup in res.fetchall() ]
    
    if 'users' in tables:
        print('"users" table exists')
    else:
        print('creating "users" table...')
        curs.execute('CREATE TABLE users(name unique, email unique, pw, pwsalt, roles, tzname)')

    if 'sessions' in tables:
        print('"sessions" table exists')
    else:
        print('creating "sessions" table...')
        curs.execute('CREATE TABLE sessions(name, sessionid unique, ipaddr, starttime, refreshtime)')

    if 'uploads' in tables:
        print('"uploads" table exists')
    else:
        print('creating "uploads" table...')
        curs.execute('CREATE TABLE uploads(uploadtime, md5, size, filename, origfilename, donorname, donoremail, donorip, donoruseragent, permission, suggestdir, ifdbid, about)')


def db_add_user(db, args):
    """Create a new user.
    """
    if len(args) != 4:
        print('usage: adduser name email pw role1,role2,role3')
        return
    args = [ val.strip() for val in args ]
    name, email, pw, roles = args
    if not name or not email or not pw:
        print('name, email, pw must be nonempty')
        return
    if '@' in name:
        print('name cannot contain an "@" character')
        return
    if '@' not in email:
        print('email must contain an "@" character')
        return
    pwsalt = random_bytes(8).encode()
    salted = pwsalt + b':' + pw.encode()
    crypted = hashlib.sha1(salted).hexdigest()
    print('adding user "%s"...' % (name,))
    logging.info('CLI user=%s: adduser %s <%s>, roles=%s', get_curuser(), name, email, roles)
    curs = db.cursor()
    curs.execute('INSERT INTO users (name, email, pw, pwsalt, roles) VALUES (?, ?, ?, ?, ?)', (name, email, crypted, pwsalt, roles))


def db_user_roles(db, args):
    """Modify the roles of a user. The roles should be supplied as a
    comma-separated list, no spaces.
    """
    if len(args) != 2:
        print('usage: userroles name role1,role2,role3')
        return
    args = [ val.strip() for val in args ]
    name, roles = args
    curs = db.cursor()
    res = curs.execute('SELECT roles FROM users WHERE name = ?', (name,))
    if not res.fetchall():
        print('no such user:', name)
        return
    print('setting roles for user "%s"...' % (name,))
    logging.info('CLI user=%s: userroles %s, roles=%s', get_curuser(), name, roles)
    curs.execute('UPDATE users SET roles = ? WHERE name = ?', (roles, name))


def db_user_pw(db, args):
    """Change the password of a user.
    """
    if len(args) != 2:
        print('usage: userpw name pw')
        return
    args = [ val.strip() for val in args ]
    name, pw = args
    if not name or not pw:
        print('name, pw must be nonempty')
        return
    curs = db.cursor()
    res = curs.execute('SELECT name FROM users WHERE name = ?', (name,))
    if not res.fetchall():
        print('no such user:', name)
        return
    pwsalt = random_bytes(8).encode()
    salted = pwsalt + b':' + pw.encode()
    crypted = hashlib.sha1(salted).hexdigest()
    print('changing pw for user "%s"...' % (name,))
    logging.info('CLI user=%s: userpw %s', get_curuser(), name)
    # Log out all sessions for the old pw
    curs.execute('DELETE FROM sessions WHERE name = ?', (name,))
    curs.execute('UPDATE users SET pw = ?, pwsalt = ? WHERE name = ?', (crypted, pwsalt, name))

def db_add_upload(db, args):
    """Create a new user.
    """
    if len(args) != 4:
        print('usage: addupload file name email comments')
        return
    args = [ val.strip() for val in args ]
    filename, name, email, comments = args
    if not filename:
        print('filename must exist')
        return
    md5 = read_md5(filename)
    size = read_size(filename)
    barefilename = os.path.basename(filename)
    now = time_now()
    print('adding upload record for %s...' % (filename,))
    logging.info('CLI user=%s: addupload %s', get_curuser(), filename)
    curs = db.cursor()
    curs.execute('INSERT INTO uploads (uploadtime, md5, size, filename, origfilename, donorname, donoremail, permission, about) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (now, md5, size, barefilename, barefilename, name, email, 'cli', comments))
    
    
