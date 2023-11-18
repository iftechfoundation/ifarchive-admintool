# The file admin interface for the IF Archive

- Copyright 2023 by the Interactive Fiction Technology Foundation
- Distributed under the MIT license
- Created by Andrew Plotkin <erkyrath@eblong.com>

This is the web interface that allows administrators and volunteers to move files around the IF Archive and edit the Index files that describe them. It is *not* meant for completely public access; volunteers must be given accounts. Certain admin tasks require command-line access on the Archive server.

The service is built on Python, server-side WSGI, and a whole lot of extremely Web-1.0 HTML forms. At present there is no Javascript at all.

An overview of the contents:

- `admin.wsgi`: A Python script that handles the main web interface. This lives in /var/ifarchive/wsgi-bin.
- `tinyapp`: A general web-app framework for WSGI apps. Used by `admin.wsgi`. Lives in /var/ifarchive/wsgi-bin/lib.
- `adminlib`: App-specific support for `admin.wsgi`. Lives in /var/ifarchive/wsgi-bin/lib.
- `templates`: HTML templates for various admin pages. Lives in /var/ifarchive/lib/admintool.
- `sample.config`: Config file. Lives in /var/ifarchive/lib/ifarch.config. Note that the version in this repository is an incomplete sample. The real ifarch.config has settings for other tools (upload, ifmap).
- `css/admintool.css`: Stylesheet. Lives in /var/ifarchive/htdocs/misc.

