# Delete target on error.
# https://www.gnu.org/software/make/manual/html_node/Errors.html#Errors
# > This is almost always what you want make to do, but it is not historical
# > practice; so for compatibility, you must explicitly request it
.DELETE_ON_ERROR:

# Global tasks.
# =============================================================================
PYTHON_VERSION := python3.11
LINTER_CHECKED_DIRS := config itou tests
PGDATABASE ?= itou
ifeq ($(shell uname -s),Linux)
	REQUIREMENTS_PATH ?= requirements/dev.txt
else
	REQUIREMENTS_PATH ?= requirements/dev-mac.txt
endif

VIRTUAL_ENV ?= .venv
export PATH := $(VIRTUAL_ENV)/bin:$(PATH)

VENV_REQUIREMENT := $(VIRTUAL_ENV)

.PHONY: runserver venv buckets clean quality fix compile-deps

runserver: $(VIRTUAL_ENV)
	python manage.py runserver $(RUNSERVER_DOMAIN)

$(VIRTUAL_ENV): $(REQUIREMENTS_PATH)
	$(PYTHON_VERSION) -m venv $@
	$@/bin/pip install -r $^
	$@/bin/pip-sync $^
	touch $@

venv: $(VIRTUAL_ENV)

buckets: $(VENV_REQUIREMENT)
	python manage.py configure_bucket

PIP_COMPILE_FLAGS := --allow-unsafe --generate-hashes $(PIP_COMPILE_OPTIONS)
compile-deps: $(VENV_REQUIREMENT)
	pip-compile $(PIP_COMPILE_FLAGS) -o requirements/base.txt requirements/base.in
	pip-compile $(PIP_COMPILE_FLAGS) -o requirements/test.txt requirements/test.in
	pip-compile $(PIP_COMPILE_FLAGS) -o requirements/dev.txt requirements/dev.in

clean:
	find . -type d -name "__pycache__" -depth -exec rm -rf '{}' \;

quality: $(VENV_REQUIREMENT)
	black --check $(LINTER_CHECKED_DIRS)
	ruff check $(LINTER_CHECKED_DIRS)
	djlint --lint --check itou
	find * -type f -name '*.sh' -exec shellcheck --external-sources {} +
	python manage.py makemigrations --check --dry-run --noinput || (echo "⚠ Missing migration ⚠"; exit 1)

fast_fix: $(VENV_REQUIREMENT)
	black $(LINTER_CHECKED_DIRS)
	ruff check --fix $(LINTER_CHECKED_DIRS)
	# Use || true because `git apply` exit with an error ("error: unrecognized input") when the pipe is empty,
	# this happens when there is nothing to fix or shellcheck can't propose a fix.
	find * -type f -name '*.sh' -exec shellcheck --external-sources --format=diff {} + | git apply || true

fix: fast_fix
	djlint --reformat itou

# Django.
# =============================================================================

.PHONY: populate_db populate_db_with_cities populate_db_minimal

# After migrate
populate_db_with_cities:
	psql -d $(PGDATABASE) --quiet --file itou/fixtures/postgres/cities.sql

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

test: $(VENV_REQUIREMENT)
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

# Deployment
# =============================================================================

.PHONY: deploy_prod
deploy_prod:
	git fetch origin  # Update our local to get the latest `master`
	@echo "Pull request deployed: https://github.com/gip-inclusion/les-emplois/pulls?q=is%3Apr+is%3Amerged+sort%3Aupdated-desc+`git log --pretty=format:"%h" origin/master_clever..origin/master | tr "\n" "+"`"
	git push origin origin/master:master_clever  # Deploy by pushing the latest `master` to `master_clever`
