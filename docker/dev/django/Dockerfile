FROM python:3.7.4-alpine3.9

ENV PYTHONIOENCODING="UTF-8"
ENV PYTHONUNBUFFERED=1

ENV APP_DIR="/app"

# Add new user to run the whole thing as non-root.
RUN addgroup -S app \
    && adduser -G app -h $APP_DIR -D app

# https://pkgs.alpinelinux.org/packages
RUN apk update \
    # psycopg2 dependencies
    && apk add --virtual build-deps gcc python3-dev musl-dev \
    && apk add postgresql-dev=11.5-r0 \
    # Pillow dependencies
    && apk add jpeg-dev zlib-dev freetype-dev lcms2-dev openjpeg-dev tiff-dev tk-dev tcl-dev \
    # CFFI dependencies
    && apk add libffi-dev py-cffi \
    # Translations dependencies
    && apk add gettext \
    # GeoDjango
    # https://docs.djangoproject.com/en/dev/ref/contrib/gis/install/#install-binutils
    && apk add binutils \
    # Geospatial dependencies
    # https://docs.djangoproject.com/en/dev/ref/contrib/gis/install/geolibs
    && apk add --repository http://dl-cdn.alpinelinux.org/alpine/edge/testing geos proj gdal \
    # https://docs.djangoproject.com/en/dev/ref/django-admin/#dbshell
    && apk add postgresql-client=11.5-r0 \
    # Time zone and daylight-saving time data
    && apk add tzdata

# Fix geospatial libraries paths issues.
RUN ln -s /usr/lib/libgdal.so.20 /usr/lib/libgdal.so
RUN ln -s /usr/lib/libgeos_c.so.1 /usr/lib/libgeos_c.so
RUN ln -s /usr/lib/libproj.so.15 /usr/lib/libproj.so

RUN cp /usr/share/zoneinfo/Europe/Paris /etc/localtime \
    && echo "Europe/Paris" > /etc/timezone

# Requirements are installed here to ensure they will be cached.
COPY ./requirements /requirements
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r /requirements/dev.txt \
    && rm -rf /requirements

COPY --chown=app:app . $APP_DIR

RUN chmod +x $APP_DIR/docker/dev/django/entrypoint.sh

USER app

WORKDIR $APP_DIR

ENTRYPOINT ["./docker/dev/django/entrypoint.sh"]
