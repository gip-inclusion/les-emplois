# https://registry.hub.docker.com/r/postgis/postgis
FROM postgis/postgis:12-master

COPY ./docker/dev/postgres/maintenance /usr/local/bin/maintenance

RUN chmod +x /usr/local/bin/maintenance/*

RUN mv /usr/local/bin/maintenance/* /usr/local/bin \
    && rm -Rf /usr/local/bin/maintenance
