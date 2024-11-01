#!/bin/bash -ex

cd /var/ifarchive
python3 wsgi-bin/admin.wsgi createdb
python3 wsgi-bin/admin.wsgi adduser zarf zarf@zarfhome.com password --roles admin
chmod -R 777 logs lib/sql
