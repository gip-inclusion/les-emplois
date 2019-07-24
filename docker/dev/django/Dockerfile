FROM python:3.7-alpine

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
    && apk add postgresql-dev=11.4-r0 \
    # Pillow dependencies
    && apk add jpeg-dev zlib-dev freetype-dev lcms2-dev openjpeg-dev tiff-dev tk-dev tcl-dev \
    # CFFI dependencies
    && apk add libffi-dev py-cffi \
    # Translations dependencies
    && apk add gettext \
    # Geospatial library
    # https://docs.djangoproject.com/en/dev/ref/contrib/gis/install/geolibs
    && apk add --no-cache --repository http://dl-cdn.alpinelinux.org/alpine/edge/testing geos=3.7.2-r0 proj=6.1.0-r4 gdal=2.4.0-r3 \
    # https://docs.djangoproject.com/en/dev/ref/django-admin/#dbshell
    && apk add postgresql-client=11.4-r0 \
    # Time zone and daylight-saving time data
    && apk add tzdata

RUN cp /usr/share/zoneinfo/Europe/Paris /etc/localtime \
    && echo "Europe/Paris" > /etc/timezone

COPY ./requirements /requirements
RUN pip install --upgrade pip
RUN pip install -r /requirements/dev.txt

COPY --chown=app:app . $APP_DIR

COPY ./docker/dev/django/entrypoint.sh /
RUN chmod +x /entrypoint.sh

WORKDIR $APP_DIR

ENTRYPOINT ["/entrypoint.sh"]
