# Creating a test environment

A note on Python versions: This software requires Python 3.7 or later. 3.7 is rather archaic, but it's what the Archive server has available. Some of the code could be simplified a bit if I installed a later version, and I will do that someday, but right now everything needs to be compatible with 3.7.

## On MacOS

Clone this repo. For the purposes of these instructions, I will assume the repo is in `/Users/zarf/src/ifarchive-admintool`. Substitute your work directory as needed.

Install `httpd` and `Python3` via homebrew. (Macs come with `httpd` installed, but it's heavily restricted. It's easier to install a separate user-level `httpd` for this project.)

    brew install httpd python@3.11

Homebrew installs into `/usr/local/bin/` (Intel Macs) or `/opt/homebrew/bin` (ARM Macs), so make sure the correct directory is in your `$PATH`.

This installation of `httpd` will be available at `http://localhost:8080/`. We will set up the admintool at `http://localhost:8080/admintest`.

Install the Python modules `mod-wsgi`, `Markdown`, `Jinja2`.

    pip3 install mod-wsgi Markdown Jinja2

Update `/usr/local/etc/httpd/httpd.conf` or `/opt/homebrew/etc/httpd/httpd.conf` to include WSGI support and the admintool script, as follows.

In the LoadModule section (near the top), add one of these lines:

```
# For Intel Macs:
LoadModule wsgi_module /usr/local/lib/python3.11/site-packages/mod_wsgi/server/mod_wsgi-py311.cpython-311-darwin.so

# For ARM Macs:
LoadModule wsgi_module /opt/homebrew/lib/python3.11/site-packages/mod_wsgi/server/mod_wsgi-py311.cpython-311-darwin.so
```

In the `<IfModule alias_module>` stanza, add:

```
# For Intel Macs:
WSGIScriptAlias /admintest "/usr/local/var/www/wsgi-bin/test.wsgi"
WSGIPythonPath "/usr/local/var/www/wsgi-lib"

# For ARM Macs:
WSGIScriptAlias /admintest "/opt/homebrew/var/www/wsgi-bin/test.wsgi"
WSGIPythonPath "/opt/homebrew/var/www/wsgi-lib"
```

Then, below:

```
<Directory "/usr/local/var/www/wsgi-bin">
    AllowOverride None
    Options FollowSymLinks
    Require all granted
</Directory>

<Directory "/usr/local/var/www/wsgi-lib">
    AllowOverride None
    Options FollowSymLinks
    Require all granted
</Directory>
```

(Or `/opt/homebrew` for ARM Macs. I'm gonna stop giving both versions, sorry, keep substituting as needed.)

Create these directories that you just configured, and symlink in the appropriate files from your repo:

```
% mkdir /usr/local/var/www/wsgi-bin
% mkdir /usr/local/var/www/wsgi-lib
% ln -s /Users/zarf/src/ifarchive-admintool/admin.wsgi /usr/local/var/www/wsgi-bin/test.wsgi
% ln -s /Users/zarf/src/ifarchive-admintool/adminlib /usr/local/var/www/wsgi-lib/adminlib
% ln -s /Users/zarf/src/ifarchive-admintool/tinyapp /usr/local/var/www/wsgi-lib/tinyapp
% cp /Users/zarf/src/ifarchive-admintool/css/admintool.css /usr/local/var/www
```

(You could put the `/Users/zarf/src/ifarchive-admintool/...` paths directly into your `<Directory>` stanzas rather than creating symlinks. This is just how I did it.)

(I copied the `admintool.css`, rather than symlinking it, because Apache's config for `/usr/local/var/www` might not support symlinks.)

At this point you need to restart `httpd` to pick up the config changes:

```
% brew services restart httpd
```

Now you need to create an `test.config` file for the admintool. The `sample.config` file in the repo is configured for the live IF Archive. You will need to change most of the paths:

```
[DEFAULT]

DBFile = /Users/zarf/src/ifarchive-admintool/admin.db

IncomingDir = /Users/zarf/src/ifarchive-admintool/testincoming
TrashDir    = /Users/zarf/src/ifarchive-admintool/testtrash
ArchiveDir  = /Users/zarf/src/ifarchive-admintool/testarchive

# Must be false if your test server is on http:
SecureSite = false

[AdminTool]

AppRoot = /admintest
AppCSSURI = /admintool.css

TemplateDir = /Users/zarf/src/ifarchive-admintool/templates

LogFile = /Users/zarf/src/ifarchive-admintool/out.log

BuildScriptFile = /Users/zarf/src/ifarchive-admintool/testbuild-bg
BuildLockFile = /Users/zarf/src/ifarchive-admintool/build.lock
BuildOutputFile = /Users/zarf/src/ifarchive-admintool/build.out

# Ten days (in seconds)
MaxSessionAge = 864000

# Thirty days (in seconds)
MaxTrashAge = 2592000
```

You must also change the `configpath` line in `admin.wsgi` to refer to this new `test.config` file:

```
configpath = '/Users/zarf/src/ifarchive-admintool/test.config'
```

(Yes, this is awfully awkward. I should be using an environment variable or something.)

Create the directories mentioned above:

```
% mkdir testincoming testtrash testarchive testarchive/unprocessed
```

Create the SQLite database (which, as configured above, will be in `/Users/zarf/src/ifarchive-admintool/admin.db`). Then create an admin user for yourself:

```
% python3 admin.wsgi createdb
% python3 admin.wsgi adduser zarf zarf@zarfhome.com password --roles admin
```

You should now be able to visit `http://localhost:8080/admintest` and log in (`zarf` / `password`, as set up above).

If the login page does not appear, or logging in fails, check both the Apache error log (`/usr/local/var/log/httpd/error_log`) and the admintool log (`/Users/zarf/src/ifarchive-admintool/out.log`).

## On Linux

(have not yet written this one yet)


## Development notes

If you edit the Python modules in `tinyapp` and `adminlib`, the changes will not be visible until you restart `httpd`.

```
# On MacOS:
% brew services restart httpd

# On Linux:
% sudo apachectl restart
```

Other changes (templates, `test.config`, the `admin.wsgi` file itself) are picked up immediately and require no restart.

This test environment does not include the "Rebuild Indexes" script. (That would require more test files which have nothing to do with the admin tool per se.) So hitting that button in the admin interface will fail.

The upload script is a [separate project][upload-py], so that's not available either. You can of course copy files directly into the `testincoming` and `testarchive/unprocessed` directories. To create upload database entries for testing, use the `python3 admin.wsgi addupload` command.

[upload-py]: https://github.com/iftechfoundation/ifarchive-upload-py
