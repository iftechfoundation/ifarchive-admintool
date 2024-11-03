#!/bin/bash -e
FILE=${@: -1}
docker compose cp $FILE web:/var/ifarchive/incoming

# pop last argument https://stackoverflow.com/a/26163980/54829
set -- "${@:1:$(($#-1))}"

# echo $@ to a file to manage quoted arguments like --name=First\ Last
quoted_args="$(printf " %q" "${@}")"
tmpfile=$(mktemp /tmp/addupload.XXXXXX)

echo "python3 /var/ifarchive/wsgi-bin/admin.wsgi addupload $quoted_args /var/ifarchive/incoming/$(basename $FILE)" > $tmpfile

docker compose cp $tmpfile web:/tmp/addupload.sh
docker compose exec web bash -ex /tmp/addupload.sh
