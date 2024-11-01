#!/bin/bash -x
docker compose exec --privileged web python3 /var/ifarchive/wsgi-bin/admin.wsgi $@
