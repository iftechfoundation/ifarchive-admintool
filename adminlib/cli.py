import optparse
import hashlib

from tinyapp.util import random_bytes


def run(appinstance):
    popt = optparse.OptionParser(usage='admin.wsgi createdb | adduser | test')
    (opts, args) = popt.parse_args()

    if not args:
        print('command-line use:')
        print('  admin.wsgi createdb: create database tables')
        print('  admin.wsgi adduser name email pw roles: add a user')
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
        db_create(appinstance.db)
    elif cmd == 'adduser':
        db_add_user(appinstance.db, args)
    else:
        print('command not recognized: %s' % (cmd,))
        print('Usage: %s' % (popt.usage,))


def db_create(db):
    curs = db.cursor()
    res = curs.execute('SELECT name FROM sqlite_master')
    tables = [ tup[0] for tup in res.fetchall() ]
    if 'users' in tables:
        print('"users" table exists')
    else:
        print('creating "users" table...')
        curs.execute('CREATE TABLE users(name unique, email unique, pw, pwsalt, roles)')
    if 'sessions' in tables:
        print('"sessions" table exists')
    else:
        print('creating "sessions" table...')
        curs.execute('CREATE TABLE sessions(name, sessionid unique, ipaddr, starttime, refreshtime)')


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
    curs = db.cursor()
    curs.execute('INSERT INTO users VALUES (?, ?, ?, ?, ?)', (name, email, crypted, pwsalt, roles))
