# https://registry.hub.docker.com/r/postgis/postgis
FROM postgis/postgis:14-master

COPY ./docker/dev/postgres/maintenance /tmp/maintenance

RUN chmod +x /tmp/maintenance/*

RUN mv /tmp/maintenance/* /usr/local/bin \
    && rm -Rf /tmp/maintenance
