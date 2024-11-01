#!/bin/bash
docker compose exec --privileged web /var/ifarchive/wsgi-bin/internal-createdb.sh
