ARG PYTHON_VERSION

# Debian Buster slim variant.
FROM python:$PYTHON_VERSION-slim-buster

ARG APP_USER
ARG APP_DIR
ARG PG_MAJOR

# Inspiration
# https://github.com/azavea/docker-django/blob/1ef366/Dockerfile-slim.template
# https://github.com/docker-library/postgres/blob/9d8e24/11/Dockerfile

ENV PYTHONIOENCODING="UTF-8"
ENV PYTHONUNBUFFERED=1
# Set ipdb as the default debugger.
# https://www.andreagrandi.it/2018/10/16/using-ipdb-with-python-37-breakpoint/
ENV PYTHONBREAKPOINT=ipdb.set_trace

# Add new user to run the whole thing as non-root.
RUN set -ex \
    && addgroup $APP_USER \
    && adduser --ingroup $APP_USER --home $APP_DIR --disabled-password $APP_USER;

RUN set -ex; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      gnupg \
      curl \
      lsb-release \
    ; \
    rm -rf /var/lib/apt/lists/*;


# Add the PostgreSQL key to verify their Debian packages.
RUN curl --silent https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add -

# Add PostgreSQL's repository. It contains the most recent stable release.
RUN echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    gdal-bin \
    gettext \
    git \
    postgresql-client-$PG_MAJOR \
    jq \
    moreutils \
    --no-install-recommends

# Requirements are installed here to ensure they will be cached.
COPY ./requirements /requirements
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r /requirements/dev.txt \
    && pip uninstall psycopg[binary] -y \
    && pip install psycopg[binary] --no-binary psycopg[binary] \
    && rm -rf /requirements

COPY --chown=$APP_USER:$APP_USER ./docker/dev/django/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

USER $APP_USER

WORKDIR $APP_DIR

ENTRYPOINT ["/entrypoint.sh"]
