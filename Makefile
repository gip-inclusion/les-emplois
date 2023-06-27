# Delete target on error.
# https://www.gnu.org/software/make/manual/html_node/Errors.html#Errors
# > This is almost always what you want make to do, but it is not historical
# > practice; so for compatibility, you must explicitly request it
.DELETE_ON_ERROR:

# Global tasks.
# =============================================================================
PYTHON_VERSION := python3.11
PGDATABASE ?= itou
ifeq ($(shell uname -s),Linux)
	REQUIREMENTS_PATH := requirements/dev.txt
else
	REQUIREMENTS_PATH := requirements/dev-mac.txt
endif

VIRTUAL_ENV ?= .venv
export PATH := $(VIRTUAL_ENV)/bin:$(PATH)

ifeq ($(USE_VENV),1)
	EXEC_CMD :=
else
	EXEC_CMD := docker exec -ti itou_django
endif

.PHONY: run venv clean cdsitepackages quality fix pylint compile-deps

# Run Docker images
run:
	docker compose up

$(VIRTUAL_ENV): $(REQUIREMENTS_PATH)
	$(PYTHON_VERSION) -m venv $@
	$@/bin/pip install -r $^
ifeq ($(shell uname -s),Linux)
	$@/bin/pip-sync $^
endif
	touch $@

venv: $(VIRTUAL_ENV)

PIP_COMPILE_FLAGS := --allow-unsafe --generate-hashes $(PIP_COMPILE_OPTIONS)
compile-deps: $(VIRTUAL_ENV)
	pip-compile $(PIP_COMPILE_FLAGS) -o requirements/base.txt requirements/base.in
	pip-compile $(PIP_COMPILE_FLAGS) -o requirements/dev.txt requirements/dev.in

clean:
	find . -type d -name "__pycache__" -depth -exec rm -rf '{}' \;

cdsitepackages:
	docker exec -ti -w /usr/local/lib/$(PYTHON_VERSION)/site-packages itou_django /bin/bash

quality: $(VIRTUAL_ENV)
	black --check config/ itou/
	ruff check config/ itou/
	djlint --lint --check itou
	find * -type f -name '*.sh' -exec shellcheck --external-sources {} +

fix: $(VIRTUAL_ENV)
	black config itou
	ruff check --fix config/ itou/
	djlint --reformat itou
	# Use || true because `git apply` exit with an error ("error: unrecognized input") when the pipe is empty,
	# this happens when there is nothing to fix or shellcheck can't propose a fix.
	find * -type f -name '*.sh' -exec shellcheck --external-sources --format=diff {} + | git apply || true

pylint: $(VIRTUAL_ENV)
	pylint config itou

# Django.
# =============================================================================

.PHONY: django_admin populate_db populate_db_with_cities populate_db_minimal graph_models_itou

# make django_admin
# make django_admin COMMAND=dbshell
# make django_admin COMMAND=createsuperuser
# make --silent django_admin COMMAND="dumpdata siaes.Siae --indent=3" > itou/fixtures/django/02_siaes.json
django_admin:
	$(EXEC_CMD) django-admin $(COMMAND)

# After migrate
ifeq ($(USE_VENV),1)
populate_db_with_cities:
	psql -d $(PGDATABASE) --quiet --file itou/fixtures/postgres/cities.sql
else
populate_db_with_cities:
	docker cp itou/fixtures/postgres/* itou_postgres:/backups/
	docker exec -ti itou_postgres bash -c "psql -d itou --quiet --file backups/cities.sql"
endif

populate_db: populate_db_with_cities
	$(EXEC_CMD) bash -c "./manage.py loaddata itou/fixtures/django/*.json"
	$(EXEC_CMD) bash -c "python itou/siae_evaluations/fixtures.py"

populate_db_minimal: populate_db_with_cities
	# Load reference data used by ASP-related code
	$(EXEC_CMD) bash -c "./manage.py loaddata itou/fixtures/django/*asp_INSEE*.json"

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
	$(EXEC_CMD) ./manage.py $(COMMAND_GRAPH_MODELS)

# Tests.
# =============================================================================

.PHONY: coverage test

test: $(VIRTUAL_ENV)
	$(EXEC_CMD) pytest --numprocesses=logical --create-db $(TARGET)

coverage:
	$(EXEC_CMD) coverage run -m pytest

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

.PHONY: psql_itou psql_root psql_to_csv

# Connect to the `itou` database as the `itou` user.
psql_itou:
	docker exec -ti -e PGPASSWORD=password itou_postgres psql -U itou -d itou

# Connect to postgres client as the `root` user.
psql_root:
	docker exec -ti itou_postgres psql -U postgres

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

.PHONY: postgres_backup postgres_backups_cp_locally postgres_backups_list postgres_backup_restore postgres_restore_latest_backup postgres_backups_clean postgres_dump_cities

postgres_backup:
	docker compose exec postgres backup

postgres_backups_cp_locally:
	docker cp itou_postgres:/backups ~/Desktop/backups

postgres_backups_list:
	docker compose exec postgres backups

# - Note: Django must be stopped to avoid a "database "itou" is being accessed by other users" error.
# make postgres_backup_restore FILE=backup_2019_10_08T12_33_00.sql.gz
# - Second note: you might get this message: `pg_restore: warning: errors ignored on restore: 331`.
# This is due to permissions on extensions and can be ignored.
# Just check you have all the data you need.
postgres_backup_restore:
	# Copy the backup file in the container first.
	# Example: docker cp FILE itou_postgres:/backups/
	docker compose up -d --no-deps postgres && \
	docker compose exec postgres restore $(FILE) && \
	docker compose stop

# Download last prod backup and inject it locally.
# ----------------------------------------------------
# Prerequisites:
# - Clone the git `itou-backups` project first and run `make build`. https://github.com/betagouv/itou-backups
# - Copy .env.template and set correct values.
postgres_restore_latest_backup: ./scripts/import-latest-db-backup.sh
	./scripts/import-latest-db-backup.sh

postgres_backups_clean:
	docker compose exec postgres clean

postgres_dump_cities:
	docker exec -ti itou_postgres bash -c "pg_dump --no-owner --no-privileges --data-only -d itou -t cities_city > /backups/cities.sql"
	docker cp itou_postgres:/backups/cities.sql itou/fixtures/postgres/

# Itou theme
# =============================================================================

.PHONY: update_itou_theme
update_itou_theme:
	docker exec itou_django /bin/sh -c "./scripts/upload_itou_theme.sh"

# Deployment
# =============================================================================

.PHONY: deploy_prod
deploy_prod:
	./scripts/deploy_prod.sh
