# The file admin interface for the IF Archive

- Copyright 2023 by the Interactive Fiction Technology Foundation
- Distributed under the MIT license
- Created by Andrew Plotkin <erkyrath@eblong.com>

This is the web interface that allows administrators and volunteers to move files around the IF Archive and edit the Index files that describe them.

The web service maintains a list of users (including administrators). This uses a traditional web login process with authentication cookies. However, accounts are *not* self-service; each account must be created by an admin with command-line access.

(We assume that admins have login accounts on the Archive server. Other volunteers do not; they can only log in through the web service.)

The service is built on Python, server-side WSGI, and a whole lot of extremely Web-1.0 HTML forms. At present there is no Javascript at all.

## Contents

- `admin.wsgi`: A Python script that handles the main web interface. This lives in /var/ifarchive/wsgi-bin.
- `tinyapp`: A general web-app framework for WSGI apps. Used by `admin.wsgi`. Lives in /var/ifarchive/wsgi-bin/lib.
- `adminlib`: App-specific support for `admin.wsgi`. Lives in /var/ifarchive/wsgi-bin/lib.
- `templates`: HTML templates for various admin pages. Lives in /var/ifarchive/lib/admintool.
- `sample.config`: Config file. Lives in /var/ifarchive/lib/ifarch.config. Note that the version in this repository is an incomplete sample. The real ifarch.config has settings for other tools (upload, ifmap).
- `css/admintool.css`: Stylesheet. Lives in /var/ifarchive/htdocs/misc.

The tool also makes use of the SQLite database in /var/ifarchive/lib/sql. This 

## Command-line use

    python3 /var/ifarchive/wsgi-bin/admin.wsgi

This will show you a list of command-line commands.

## Testing

It is possible to test the admin interface on a local Apache server. I have not yet written up the procedure; apologies.
