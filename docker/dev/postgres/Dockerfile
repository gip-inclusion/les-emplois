FROM mdillon/postgis:11

COPY ./docker/dev/postgres/maintenance /usr/local/bin/maintenance

RUN chmod +x /usr/local/bin/maintenance/*

RUN mv /usr/local/bin/maintenance/* /usr/local/bin \
    && rm -Rf /usr/local/bin/maintenance
