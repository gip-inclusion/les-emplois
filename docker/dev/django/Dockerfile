# Debian Buster slim variant.
FROM python:3.9.12-slim-buster

ENV DOCKER_DEFAULT_PLATFORM=linux/amd64
# Inspiration
# https://github.com/azavea/docker-django/blob/1ef366/Dockerfile-slim.template
# https://github.com/docker-library/postgres/blob/9d8e24/11/Dockerfile

ENV PYTHONIOENCODING="UTF-8"
ENV PYTHONUNBUFFERED=1
# Set ipdb as the default debugger.
# https://www.andreagrandi.it/2018/10/16/using-ipdb-with-python-37-breakpoint/
ENV PYTHONBREAKPOINT=ipdb.set_trace

ENV APP_DIR="/app"

# Add new user to run the whole thing as non-root.
RUN set -ex \
    && addgroup app \
    && adduser --ingroup app --home $APP_DIR --disabled-password app;

RUN set -ex; \
    if ! command -v gpg > /dev/null; then \
        apt-get update; \
        apt-get install -y --no-install-recommends \
            gnupg \
            dirmngr \
        ; \
        rm -rf /var/lib/apt/lists/*; \
    fi

# Add the PostgreSQL PGP key to verify their Debian packages.
RUN set -ex; \
# pub   4096R/ACCC4CF8 2011-10-13 [expires: 2019-07-02]
#       Key fingerprint = B97B 0AFC AA1A 47F0 44F2  44A0 7FCC 7D46 ACCC 4CF8
# uid                  PostgreSQL Debian Repository
    key='B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8'; \
    export GNUPGHOME="$(mktemp -d)"; \
    gpg --batch --keyserver keyserver.ubuntu.com --recv-keys "$key"; \
    gpg --batch --export "$key" > /etc/apt/trusted.gpg.d/postgres.gpg; \
    command -v gpgconf > /dev/null && gpgconf --kill all; \
    rm -rf "$GNUPGHOME"; \
    apt-key list;

ENV PG_MAJOR="14"

# Add PostgreSQL's repository. It contains the most recent stable release.
RUN echo "deb http://apt.postgresql.org/pub/repos/apt/ buster-pgdg main $PG_MAJOR" > /etc/apt/sources.list.d/pgdg.list

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    gdal-bin \
    gettext \
    git \
    postgresql-client-$PG_MAJOR \
    --no-install-recommends

# Requirements are installed here to ensure they will be cached.
COPY ./requirements /requirements
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r /requirements/dev.txt \
    && pip uninstall psycopg2-binary -y \
    && pip install psycopg2-binary --no-binary psycopg2-binary \
    && rm -rf /requirements

RUN apt-get purge -y --auto-remove build-essential libpq-dev $(! command -v gpg > /dev/null || echo 'gnupg dirmngr') \
    && rm -rf /var/lib/apt/lists/*

COPY --chown=app:app . $APP_DIR

RUN chmod +x $APP_DIR/docker/dev/django/entrypoint.sh

USER app

WORKDIR $APP_DIR

ENTRYPOINT ["./docker/dev/django/entrypoint.sh"]
