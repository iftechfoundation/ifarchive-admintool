FROM ubuntu:noble

RUN apt-get update -y && apt-get install -y apache2 apache2-dev libapache2-mod-wsgi-py3 python3 python3-pip

RUN pip3 install --break-system-packages mod-wsgi
RUN pip3 install --break-system-packages Jinja2
RUN pip3 install --break-system-packages pytz

RUN <<EOF
mkdir /var/ifarchive
cd /var/ifarchive
mkdir lib lib/sql lib/admintool
mkdir incoming trash logs wsgi-bin
mkdir htdocs htdocs/misc htdocs/if-archive htdocs/if-archive/unprocessed htdocs/if-archive/games
chmod -R 777 .
EOF

COPY sample.config /var/ifarchive/lib/ifarch.config
RUN sed -i 's/SecureSite = true/SecureSite = false/g' /var/ifarchive/lib/ifarch.config
COPY ifarchive-admintool.conf /etc/apache2/sites-available

COPY docker/internal-createdb.sh /var/ifarchive/wsgi-bin
RUN chmod 777 /var/ifarchive/wsgi-bin/internal-createdb.sh

RUN a2dissite 000-default
RUN a2ensite ifarchive-admintool

CMD apachectl -D FOREGROUND
