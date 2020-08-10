# Global tasks.
# =============================================================================

.PHONY: run clean cdsitepackages quality style setup_git_pre_commit_hook

# Run a local server.
run:
	docker-compose up

clean:
	find . -type d -name "__pycache__" -depth -exec rm -rf '{}' \;

cdsitepackages:
	docker exec -ti -w /usr/local/lib/python3.7/site-packages itou_django /bin/bash

quality:
	docker exec -ti itou_django black --check --line-length 119 itou
	docker exec -ti itou_django isort --check-only itou
	docker exec -ti itou_django flake8 itou

style:
	docker exec -ti itou_django black --line-length 119 itou
	docker exec -ti itou_django isort itou

setup_git_pre_commit_hook:
	touch .git/hooks/pre-commit
	chmod +x .git/hooks/pre-commit
	echo "\
	docker exec -t itou_django black --line-length 119 itou\n\
	docker exec -t itou_django isort itou\n\
	" > .git/hooks/pre-commit

# Django.
# =============================================================================

.PHONY: django_admin populate_db

# make django_admin
# make django_admin COMMAND=dbshell
# make django_admin COMMAND=createsuperuser
# make django_admin COMMAND="dumpdata siaes.Siae" > ~/Desktop/siaes.json
django_admin:
	docker exec -ti itou_django django-admin $(COMMAND)

populate_db:
	docker cp itou/fixtures/postgres/* itou_postgres:/backups/
	docker exec -ti itou_postgres bash -c "psql -d itou -f backups/cities.sql"
	docker exec -ti itou_django bash -c "ls -d itou/fixtures/django/* | xargs django-admin loaddata"

# Tests.
# =============================================================================

.PHONY: test

# make test
# make test TARGET=itou.utils
# make test TARGET=itou.utils.tests.UtilsTemplateTagsTestCase.test_url_add_query
test:
	docker exec -ti itou_django django-admin test --settings=config.settings.test --noinput --failfast --parallel=2 $(TARGET)

# Lets you add a debugger.
test-interactive:
	docker exec -ti itou_django django-admin test --settings=config.settings.test --failfast $(TARGET)

# Docker shell.
# =============================================================================

.PHONY: shell_on_django_container shell_on_django_container_as_root shell_on_postgres_container

shell_on_django_container:
	docker exec -ti itou_django /bin/bash

shell_on_django_container_as_root:
	docker exec -ti --user root itou_django /bin/bash

shell_on_postgres_container:
	docker exec -ti itou_postgres /bin/bash

# Postgres CLI.
# =============================================================================

.PHONY: psql_itou psql_root

# Connect to the `itou` database as the `itou` user.
psql_itou:
	docker exec -ti -e PGPASSWORD=password itou_postgres psql -U itou -d itou

# Connect to postgres client as the `root` user.
psql_root:
	docker exec -ti -e PGPASSWORD=password itou_postgres psql -U postgres

# Postgres (backup / restore).
# Inspired by:
# https://cookiecutter-django.readthedocs.io/en/latest/docker-postgres-backups.html
# =============================================================================

.PHONY: postgres_backup postgres_backups_cp_locally postgres_backups_list postgres_backup_restore postgres_backups_clean

postgres_backup:
	docker-compose exec postgres backup

postgres_backups_cp_locally:
	docker cp itou_postgres:/backups ~/Desktop/backups

postgres_backups_list:
	docker-compose exec postgres backups

# - Note: Django must be stopped to avoid a "database "itou" is being accessed by other users" error.
# make postgres_backup_restore FILE=backup_2019_10_08T12_33_00.sql.gz
# - Second note: you might get this message: `pg_restore: warning: errors ignored on restore: 331`.
# This is due to permissions on extensions and can be ignored.
# Just check you have all the data you need.
postgres_backup_restore:
	# Copy the backup file in the container first.
	# Example: docker cp FILE itou_postgres:/backups/
	docker-compose up -d --no-deps postgres && \
	docker-compose exec postgres restore $(FILE) && \
	docker-compose stop

postgres_backups_clean:
	docker-compose exec postgres clean

postgres_dump_cities:
	docker exec -ti itou_postgres bash -c "pg_dump -d itou -t cities_city > /backups/cities.sql"
	docker cp itou_postgres:/backups/cities.sql itou/fixtures/postgres/

# Delete and recreate the DB manually.
# =============================================================================
# docker-compose down
# docker-compose up --no-deps postgres
# make shell_on_postgres_container
# PGPASSWORD=password psql -h postgres -U postgres
# DROP DATABASE itou;
# CREATE DATABASE itou OWNER itou;
