# Global tasks.
# =============================================================================

.PHONY: clean cdsitepackages

clean:
	find . -type d -name "__pycache__" -depth -exec rm -rf '{}' \;

cdsitepackages:
	docker exec -ti -w /usr/local/lib/python3.7/site-packages itou_django /bin/sh

# Django.
# =============================================================================

.PHONY: django_admin

# make django_admin
# make django_admin COMMAND=dbshell
# make django_admin COMMAND=createsuperuser
# make django_admin COMMAND="dumpdata siae.Siae" > ~/Desktop/siae.json
django_admin:
	docker exec -ti itou_django django-admin $(COMMAND)

# Tests.
# =============================================================================

.PHONY: test

test:
	docker exec -ti itou_django django-admin test --settings=config.settings.test --noinput

# Docker shell.
# =============================================================================

.PHONY: shell_on_django_container shell_on_postgres_container

shell_on_postgres_container:
	docker exec -ti itou_postgres /bin/sh

shell_on_django_container:
	docker exec -ti itou_django /bin/sh

# Postgres (dev).
# =============================================================================

.PHONY: dbshell_dev_itou dbshell_dev_root dump_db

# Connect to the `itou` database as the `itou` user.
dbshell_dev_itou:
	docker exec -ti -e PGPASSWORD=password itou_django psql -p 5432 -h postgres -U itou itou

# Connect to postgres client as the `root` user.
dbshell_dev_root:
	docker exec -ti -e PGPASSWORD=password itou_django psql -p 5432 -h postgres -U postgres

dump_db:
	docker exec -ti -e PGPASSWORD=password itou_django pg_dump -p 5432 -h postgres -U itou itou > ~/Desktop/itou.sql

# docker-compose -f docker-compose-dev.yml up --no-deps postgres
# make shell_on_postgres_container
# psql -h postgres -U postgres
# DROP DATABASE itou;
# CREATE DATABASE itou OWNER itou;
# \c itou;
# CREATE EXTENSION postgis;
