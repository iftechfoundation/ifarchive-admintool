# The file admin interface for the IF Archive

- Copyright 2023 by the Interactive Fiction Technology Foundation
- Distributed under the MIT license
- Created by Andrew Plotkin <erkyrath@eblong.com>

This is the web interface that allows administrators and volunteers to move files around the IF Archive and edit the `Index` files that describe them.

The web service maintains a list of users (including administrators). This uses a traditional web login process with authentication cookies. However, accounts are *not* self-service; each account must be created by an admin with command-line access.

(We assume that admins have login accounts on the Archive server. Other volunteers do not; their only access is through the web service.)

The service is built on Python, server-side WSGI, and a whole lot of extremely Web-1.0 HTML forms. At present there is no Javascript at all.

## Principles

We separate the work into roles as much as possible. A user can have any number of roles. The current roles are:

- "incoming": Move files from /incoming to /unprocessed.
- "filing": Move files from /unprocessed to other archive directories.
- "index": Edit `Index` files.
- "rebuild": Run `build-indexes` to regenerate the Archive's public index pages.
- "admin": Do everything.

It should not be possible to destroy or overwrite files from the web service. Mistakes should always be recoverable, although it might take an admin to untangle serious problems.

Thus, "deleting" a file moves it to the /trash directory, where it will live for at least 30 days. Similarly, whenever you edit an `Index` file, the previous version is copied to /trash.

All activity is logged. (The log is not viewable from the web service; you need command-line access to see it.)

## Contents

- `admin.wsgi`: A Python script that handles the main web interface. This lives in /var/ifarchive/wsgi-bin.
- `tinyapp`: A general web-app framework for WSGI apps. Used by `admin.wsgi`. Lives in /var/ifarchive/wsgi-bin/lib.
- `adminlib`: App-specific support for `admin.wsgi`. Lives in /var/ifarchive/wsgi-bin/lib.
- `templates`: HTML templates for various admin pages. Lives in /var/ifarchive/lib/admintool.
- `sample.config`: Config file. Lives in /var/ifarchive/lib/ifarch.config. Note that the version in this repository is an incomplete sample. The real ifarch.config has settings for other tools (upload, ifmap).
- `css/admintool.css`: Stylesheet. Lives in /var/ifarchive/htdocs/misc.

The tool also makes use of the SQLite database in /var/ifarchive/lib/sql. This must be writable by both Apache and the admins.

## Command-line use

    python3 /var/ifarchive/wsgi-bin/admin.wsgi

This will display a list of command-line commands.

## Testing

It is possible to test the admin interface on a local Apache server. I have not yet written up the procedure; apologies.
