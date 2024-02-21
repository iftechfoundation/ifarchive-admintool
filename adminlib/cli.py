import argparse
import os, os.path
import time
import hashlib
import logging

from tinyapp.util import random_bytes, time_now

def run(appinstance):
    """The entry point when admin.wsgi is invoked on the command line.
    """
    popt = argparse.ArgumentParser(prog='admin.wsgi')
    subopt = popt.add_subparsers(dest='cmd', title='commands')

    popt_cleanup = subopt.add_parser('cleanup', help='clean out trash, etc')
    popt_cleanup.set_defaults(cmdfunc=cmd_cleanup)
    
    popt_adduser = subopt.add_parser('adduser', help='add a user')
    popt_adduser.set_defaults(cmdfunc=cmd_adduser)
    popt_adduser.add_argument('name')
    popt_adduser.add_argument('email')
    popt_adduser.add_argument('pw', help='password')
    popt_adduser.add_argument('--roles', '--role', default='', help='(ROLES can be a comma-separated list)')
    
    popt_edituser = subopt.add_parser('edituser', help='change a user\'s roles or password')
    popt_edituser.set_defaults(cmdfunc=cmd_edituser)
    popt_edituser.add_argument('name')
    popt_edituser.add_argument('--pw', metavar='PASSWORD')
    popt_edituser.add_argument('--roles', '--role', default='', help='(ROLES can be a comma-separated list)')
    
    popt_createdb = subopt.add_parser('createdb', help='create database tables')
    popt_createdb.set_defaults(cmdfunc=cmd_createdb)
    
    popt_addupload = subopt.add_parser('addupload', help='add a file to the upload log')
    popt_addupload.set_defaults(cmdfunc=cmd_addupload)
    popt_addupload.add_argument('file')
    popt_addupload.add_argument('--name')
    popt_addupload.add_argument('--email')
    popt_addupload.add_argument('--tempid')
    popt_addupload.add_argument('--ifid')
    popt_addupload.add_argument('--origfile')
    popt_addupload.add_argument('--dir')
    popt_addupload.add_argument('-m', '--message')
    
    popt_test = subopt.add_parser('test', help='print page to stdout')
    popt_test.set_defaults(cmdfunc=cmd_test)
    popt_test.add_argument('uri', nargs='?', default='', metavar='URI')
    
    args = popt.parse_args()

    if not args.cmd:
        popt.print_help()
        return

    args.cmdfunc(args, appinstance)


def get_curuser():
    """getlogin() fails sometimes, I dunno why. (I see it happening
    when running in the web server, but I don't know that it *can't*
    happen on the command line.) So we catch exceptions.
    """
    try:
        return os.getlogin()
    except:
        return '???'
        

def cmd_test(args, app):
    """Test generating one page (to stdout).
    """
    app.test_dump(args.uri)
    
    
def cmd_cleanup(args, app):
    """Clean up stuff that needs to be cleaned up periodically.
    Should be run from a cron job.
    """
    logging.info('CLI user=%s: cleanup', get_curuser())

    # Clean out old sessions. Note that in the sessions table
    # (refreshtime >= starttime), so we just look at refreshtime.
    timelimit = time.time() - app.max_session_age
    curs = app.getdb().cursor()
    res = curs.execute('DELETE FROM sessions WHERE refreshtime < ?', (timelimit,))

    # Clean out old trash files.
    timelimit = time.time() - app.max_trash_age
    # We clean up "Index*" files in a quarter the time, because wow
    # there are a lot of them.
    indextimelimit = time.time() - app.max_trash_age / 4
    
    dells = []
    for ent in os.scandir(app.trash_dir):
        if ent.is_file():
            stat = ent.stat()
            uselimit = timelimit
            if ent.name.startswith('Index-'):
                uselimit = indextimelimit
            if stat.st_mtime < uselimit:
                dells.append(ent.name)

    for name in dells:
        print('Deleting "%s" from trash...' % (name,))
        pathname = os.path.join(app.trash_dir, name)
        os.remove(pathname)

def cmd_createdb(args, app):
    """Create the database tables. This only needs to be done once ever,
    unless of course we change the table structure or decide to wipe
    and start over.
    TODO: Add a column if it doesn't exist?
    """
    logging.info('CLI user=%s: createdb', get_curuser())
    curs = app.getdb().cursor()
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
        curs.execute('CREATE TABLE uploads(uploadtime, md5, size, filename, origfilename, donorname, donoremail, donorip, donoruseragent, permission, suggestdir, ifdbid, about, usernotes, ifid)')


def cmd_adduser(args, app):
    """Create a new user.
    """
    if not args.name or not args.email or not args.pw:
        print('name, email, pw must be nonempty')
        return
    if '@' in args.name:
        print('name cannot contain an "@" character')
        return
    if '@' not in args.email:
        print('email must contain an "@" character')
        return
    pwsalt = random_bytes(8).encode()
    salted = pwsalt + b':' + args.pw.encode()
    crypted = hashlib.sha1(salted).hexdigest()
    print('adding user "%s"...' % (args.name,))
    logging.info('CLI user=%s: adduser %s <%s>, roles=%s', get_curuser(), args.name, args.email, args.roles)
    curs = app.getdb().cursor()
    curs.execute('INSERT INTO users (name, email, pw, pwsalt, roles) VALUES (?, ?, ?, ?, ?)', (args.name, args.email, crypted, pwsalt, args.roles))


def cmd_edituser(args, app):
    """Modify the password or roles of a user.
    """
    curs = app.getdb().cursor()
    res = curs.execute('SELECT roles FROM users WHERE name = ?', (args.name,))
    if not res.fetchall():
        print('no such user:', args.name)
        return
    if args.roles:
        print('setting roles for user "%s"...' % (args.name,))
        logging.info('CLI user=%s: edituser %s, roles=%s', get_curuser(), args.name, args.roles)
        curs.execute('UPDATE users SET roles = ? WHERE name = ?', (args.roles, args.name))
    if args.pw:
        pwsalt = random_bytes(8).encode()
        salted = pwsalt + b':' + args.pw.encode()
        crypted = hashlib.sha1(salted).hexdigest()
        print('changing pw for user "%s"...' % (args.name,))
        logging.info('CLI user=%s: edituser %s, pw=...', get_curuser(), args.name)
        # Log out all sessions for the old pw
        curs.execute('DELETE FROM sessions WHERE name = ?', (args.name,))
        curs.execute('UPDATE users SET pw = ?, pwsalt = ? WHERE name = ?', (crypted, pwsalt, args.name))


def cmd_addupload(args, app):
    """Create a new upload record.
    """
    filename = args.file
    md5, size = app.hasher.get_md5_size(filename)
    barefilename = os.path.basename(filename)
    origfile = args.origfile or barefilename
    now = time_now()
    print('adding upload record for %s...' % (filename,))
    logging.info('CLI user=%s: addupload %s', get_curuser(), filename)
    curs = app.getdb().cursor()
    curs.execute('INSERT INTO uploads (uploadtime, md5, size, filename, origfilename, donorname, donoremail, permission, suggestdir, ifdbid, about, ifid) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (now, md5, size, barefilename, origfile, args.name, args.email, 'cli', args.dir, args.tempid, args.message, args.ifid))
    
    
