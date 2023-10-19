import optparse
import os
import hashlib
import logging

from tinyapp.util import random_bytes

def run(appinstance):
    popt = optparse.OptionParser(usage='admin.wsgi createdb | adduser | userroles | userpw | test')
    (opts, args) = popt.parse_args()

    if not args:
        print('command-line use:')
        print('  admin.wsgi createdb: create database tables')
        print('  admin.wsgi adduser name email pw roles: add a user')
        print('  admin.wsgi userroles name roles: change a user\'s roles')
        print('  admin.wsgi userpw name pw: change a user\'s password')
        print('  admin.wsgi test [ URI ]: print page to stdout')
        ### cleanup
        return

    cmd = args.pop(0)
    
    if cmd == 'test':
        uri = ''
        if args:
            uri = args[0]
        appinstance.test_dump(uri)
    elif cmd == 'createdb':
        db_create(appinstance.getdb())
    elif cmd == 'adduser':
        db_add_user(appinstance.getdb(), args)
    elif cmd == 'userroles':
        db_user_roles(appinstance.getdb(), args)
    elif cmd == 'userpw':
        db_user_pw(appinstance.getdb(), args)
    else:
        print('command not recognized: %s' % (cmd,))
        print('Usage: %s' % (popt.usage,))

def get_curuser():
    """This fails sometimes, I dunno why. So we catch exceptions.
    """
    try:
        return os.getlogin()
    except:
        return '???'
        

def db_create(db):
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
