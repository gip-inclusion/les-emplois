# Delete target on error.
# https://www.gnu.org/software/make/manual/html_node/Errors.html#Errors
# > This is almost always what you want make to do, but it is not historical
# > practice; so for compatibility, you must explicitly request it
.DELETE_ON_ERROR:

# Global tasks.
# =============================================================================
PYTHON_VERSION := python3.11
LINTER_CHECKED_DIRS := config itou scripts tests
PGDATABASE ?= itou
REQUIREMENTS_PATH ?= requirements/dev.txt

VIRTUAL_ENV ?= .venv
export PATH := $(VIRTUAL_ENV)/bin:$(PATH)

.PHONY: runserver venv buckets clean quality fix compile-deps

runserver: $(VIRTUAL_ENV)
	python manage.py runserver $(RUNSERVER_DOMAIN)

$(VIRTUAL_ENV): $(REQUIREMENTS_PATH)
	$(PYTHON_VERSION) -m venv $@
	$@/bin/pip install uv
	$@/bin/uv pip sync --require-hashes $^
	touch $@

venv: $(VIRTUAL_ENV)

buckets: $(VIRTUAL_ENV)
	python manage.py configure_bucket

PIP_COMPILE_FLAGS := --no-strip-extras --generate-hashes $(PIP_COMPILE_OPTIONS)
compile-deps: $(VIRTUAL_ENV)
	uv pip compile $(PIP_COMPILE_FLAGS) -o requirements/base.txt requirements/base.in
	uv pip compile $(PIP_COMPILE_FLAGS) -o requirements/test.txt requirements/test.in
	uv pip compile $(PIP_COMPILE_FLAGS) -o requirements/dev.txt requirements/dev.in

clean:
	find . -type d -name "__pycache__" -depth -exec rm -rf '{}' \;

quality: $(VIRTUAL_ENV)
	ruff format --check $(LINTER_CHECKED_DIRS)
	ruff check $(LINTER_CHECKED_DIRS)
	djlint --lint --check itou
	find * -type f -name '*.sh' -exec shellcheck --external-sources {} +
	python manage.py makemigrations --check --dry-run --noinput || (echo "⚠ Missing migration ⚠"; exit 1)
	python manage.py collectstatic --no-input
	# Make sure pytest help is still accessible.
	pytest --help >/dev/null

fast_fix: $(VIRTUAL_ENV)
	ruff format $(LINTER_CHECKED_DIRS)
	ruff check --fix $(LINTER_CHECKED_DIRS)
	find * -type f -name '*.sh' -exec shellcheck --external-sources --format=diff {} + | git apply --allow-empty

fix: fast_fix
	djlint --reformat itou

# Django.
# =============================================================================

.PHONY: populate_db populate_db_with_cities populate_db_minimal

# After migrate
populate_db_with_cities: $(VIRTUAL_ENV)
	python manage.py dbshell <itou/fixtures/postgres/cities.sql

populate_db: populate_db_with_cities
	# Split loaddata_bulk into parts to avoid OOM errors in review apps
	python manage.py loaddata_bulk itou/fixtures/django/01_*.json
	python manage.py loaddata_bulk itou/fixtures/django/0[2-9]_*.json
	python manage.py loaddata_bulk itou/fixtures/django/1*.json
	python manage.py loaddata_bulk itou/fixtures/django/2*.json
	python manage.py shell -c 'from itou.siae_evaluations import fixtures;fixtures.load_data()'

populate_db_minimal: populate_db_with_cities
	# Load reference data used by ASP-related code
	python manage.py loaddata_bulk itou/fixtures/django/*asp_INSEE*.json

# Tests.
# =============================================================================

.PHONY: test

test: $(VIRTUAL_ENV)
	pytest --numprocesses=logical --create-db $(TARGET)

# Docker shell.
# =============================================================================

.PHONY: shell_on_django_container shell_on_django_container_as_root shell_on_postgres_container

shell_on_django_container:
	docker exec -ti itou_django /bin/bash

shell_on_django_container_as_root:
	docker exec -ti --user root itou_django /bin/bash

shell_on_postgres_container:
	docker exec -ti itou_postgres /bin/bash

# Database.
# =============================================================================

.PHONY: restore_latest_backup

restore_latest_backup:
	./scripts/restore_latest_backup.sh $(PGDATABASE)
