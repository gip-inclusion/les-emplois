ARG PYTHON_VERSION

# https://hub.docker.com/_/python
FROM python:$PYTHON_VERSION-slim

ARG APP_USER
ARG APP_DIR
ARG PG_MAJOR
ARG XDG_CACHE_HOME="/app_cache"

VOLUME $XDG_CACHE_HOME

# Inspiration
# https://github.com/azavea/docker-django/blob/1ef366/Dockerfile-slim.template
# https://github.com/docker-library/postgres/blob/9d8e24/11/Dockerfile

ENV PYTHONIOENCODING="UTF-8"
ENV PYTHONUNBUFFERED=1
# Set ipdb as the default debugger.
# https://www.andreagrandi.it/2018/10/16/using-ipdb-with-python-37-breakpoint/
ENV PYTHONBREAKPOINT=ipdb.set_trace
ENV XDG_CACHE_HOME=$XDG_CACHE_HOME

# Install tools to setup the PostgreSQL reposity
RUN set -ex; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      curl \
      lsb-release \
    ; \
    rm -rf /var/lib/apt/lists/*;
# Add the PostgreSQL key to verify their Debian packages.
RUN curl --silent https://www.postgresql.org/media/keys/ACCC4CF8.asc --output /etc/apt/keyrings/postgresql.asc --create-dirs
# Add PostgreSQL's repository. It contains the most recent stable release.
RUN echo "deb [signed-by=/etc/apt/keyrings/postgresql.asc] http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    gdal-bin \
    git \
    postgresql-client-$PG_MAJOR \
    jq \
    moreutils \
    python3-venv \
    --no-install-recommends

# Add new user to run the whole thing as non-root.
RUN set -ex \
    && addgroup $APP_USER \
    && adduser --ingroup $APP_USER --home /home --disabled-password $APP_USER;

RUN echo '. "$VIRTUAL_ENV"/bin/activate' >> /home/.bashrc

# Setup app cache dir
RUN mkdir -p $XDG_CACHE_HOME \
    && chown $APP_USER: $XDG_CACHE_HOME

# Setup the entrypoint
COPY --chown=$APP_USER:$APP_USER --chmod=755 ./docker/dev/django/entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

# Don't use root as default user
USER $APP_USER
WORKDIR $APP_DIR
