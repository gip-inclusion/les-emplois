# Global tasks.
# =============================================================================
PYTHON_VERSION := python3.9

.PHONY: run clean cdsitepackages quality

# Run Docker images
run:
	docker-compose up

clean:
	find . -type d -name "__pycache__" -depth -exec rm -rf '{}' \;

cdsitepackages:
	docker exec -ti -w /usr/local/lib/$(PYTHON_VERSION)/site-packages itou_django /bin/bash

quality:
	docker exec -ti itou_django black itou
	docker exec -ti itou_django isort itou
	docker exec -ti itou_django flake8 itou

quality_venv:
	black itou
	isort itou
	flake8 itou

pylint:
	docker exec -ti itou_django pylint itou

coverage:
	docker exec -ti itou_django coverage run ./manage.py test itou --settings=config.settings.test
	docker exec -ti itou_django coverage html

coverage_venv:
	coverage run ./manage.py test itou --settings=config.settings.test && coverage html

# Django.
# =============================================================================

.PHONY: django_admin populate_db

# make django_admin
# make django_admin COMMAND=dbshell
# make django_admin COMMAND=createsuperuser
# make --silent django_admin COMMAND="dumpdata siaes.Siae --indent=3" > itou/fixtures/django/02_siaes.json
django_admin:
	docker exec -ti itou_django django-admin $(COMMAND)

# After migrate
populate_db:
	docker cp itou/fixtures/postgres/* itou_postgres:/backups/
	docker exec -ti itou_postgres bash -c "pg_restore -d itou --if-exists --clean --no-owner --no-privileges backups/cities.sql"
	docker exec -ti itou_django bash -c "ls -d itou/fixtures/django/* | xargs django-admin loaddata"

populate_db_venv:
	pg_restore -d itou --if-exists --clean --no-owner --no-privileges itou/fixtures/postgres/cities.sql
	ls -d itou/fixtures/django/* | xargs ./manage.py loaddata

COMMAND_GRAPH_MODELS := graph_models --group-models \
	approvals \
	asp \
	cities \
	eligibility \
	employee_record \
	external_data \
	institutions \
	invitations \
	job_applications \
	jobs \
	prescribers \
	siaes \
	users \
	--pygraphviz -o itou-graph-models.svg

# Install these packages first:
# apt-get install gcc graphviz graphviz-dev
# pip install pygraphviz
graph_models_itou:
	docker exec -ti itou_django django-admin $(COMMAND_GRAPH_MODELS)

graph_models_itou_venv:
	./manage.py $(COMMAND_GRAPH_MODELS)

# Tests.
# =============================================================================

.PHONY: test

test:
	docker exec -ti itou_django django-admin test --settings=config.settings.test $(TARGET) --noinput --failfast --parallel

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

# Write query results to a CSV file.
# --
# make psql_to_csv FILEPATH=path/to/script.sql
# make psql_to_csv FILEPATH=path/to/script.sql EXPORTNAME=extract.csv
psql_to_csv:
	docker cp $(FILEPATH) itou_postgres:/script.sql
	docker exec -ti -e PGPASSWORD=password itou_postgres psql -U itou -d itou --csv -f /script.sql -o /export.csv
	docker cp itou_postgres:/export.csv exports/$(EXPORTNAME)
	docker exec -ti itou_postgres rm /script.sql /export.csv

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

# Download last prod backup and inject it locally.
# ----------------------------------------------------
# Prerequisites:
# - Clone the git `itou-backups` project first and run `make build`. https://github.com/betagouv/itou-backups
# - Copy .env.template and set correct values.
postgres_restore_latest_backup: ./scripts/import-latest-db-backup.sh
	./scripts/import-latest-db-backup.sh

postgres_backups_clean:
	docker-compose exec postgres clean

postgres_dump_cities:
	docker exec -ti itou_postgres bash -c "pg_dump --clean --if-exists --format c --no-owner --no-privileges -d itou -t cities_city > /backups/cities.sql"
	docker cp itou_postgres:/backups/cities.sql itou/fixtures/postgres/

# Itou theme
# =============================================================================

update_itou_theme:
	docker exec itou_django /bin/sh -c "./scripts/upload_itou_theme.sh"

# Deployment
# =============================================================================

deploy_prod:
	./scripts/deploy_prod.sh
