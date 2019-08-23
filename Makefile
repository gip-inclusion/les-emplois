# Global tasks.
# =============================================================================

.PHONY: clean cdsitepackages pylint

clean:
	find . -type d -name "__pycache__" -depth -exec rm -rf '{}' \;

cdsitepackages:
	docker exec -ti -w /usr/local/lib/python3.7/site-packages itou_django /bin/sh

pylint:
	docker exec -ti itou_django pylint --rcfile='.pylintrc' --reports=no --output-format=colorized 'itou';

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

# make test
# make test TARGET=itou.utils
# make test TARGET=itou.utils.tests.UtilsTemplateTagsTestCase.test_url_add_query
test:
	docker exec -ti itou_django django-admin test --settings=config.settings.test --noinput --failfast --parallel=2 $(TARGET)

# Docker shell.
# =============================================================================

.PHONY: shell_on_django_container shell_on_postgres_container

shell_on_postgres_container:
	docker exec -ti itou_postgres /bin/sh

shell_on_django_container:
	docker exec -ti itou_django /bin/sh

# Postgres (dev).
# =============================================================================

.PHONY: dbshell_dev_itou dbshell_dev_root dump_db restore_db

# Connect to the `itou` database as the `itou` user.
dbshell_dev_itou:
	docker exec -ti -e PGPASSWORD=password itou_postgres psql -U itou -d itou

# Connect to postgres client as the `root` user.
dbshell_dev_root:
	docker exec -ti -e PGPASSWORD=password itou_postgres psql -U postgres

dump_db:
	docker exec -i -e PGPASSWORD=password itou_postgres pg_dump -U itou -d itou > ~/Desktop/itou.sql

restore_db:
	docker exec -i -e PGPASSWORD=password itou_postgres psql -U itou -d itou < ~/Desktop/itou.sql

# docker-compose -f docker-compose-dev.yml up --no-deps postgres
# make shell_on_postgres_container
# psql -h postgres -U postgres
# DROP DATABASE itou;
# CREATE DATABASE itou OWNER itou;
