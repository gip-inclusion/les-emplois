# AGENTS.md

## Project overview

**Les emplois de l’inclusion** is a Python/Django-based platform for issuing "PASS IAE" and connecting inclusive employers with candidates distanced from employment.

## Stack & environment

* Python 3.13, Django 6, use the latest features
* Bootstrap 5.3.8, htmx 2
* PostgreSQL 17 for database with migrations managed through Django
* Object storage via MinIO (or equivalent) for media
* Docker & Docker Compose for dependencies (see docker-compose.yml)

## Core setup & dev commands

### Install & build

```bash
# start services
docker compose up

# create development database & run migrations
make resetdb

# start Django dev server
make runserver
```

### Quality & testing

```bash
# install pre-commit hooks
pre-commit install

# run linters and formatters
make fix

# running the full test suite is quite long and resource-intensive,
# so consider running specific test modules or classes during development
make test
```

### Documentation Links

* Human-oriented docs live under `docs/`
* Swagger/OpenAPI may be present if defined (search for schema definitions)

## Project structure

```
├── docs/               # human documentation
├── itou/               # core django app code
├── requirements/       # dependency specs
├── scripts/            # tooling & automation scripts
├── tests/              # test suite
├── docker-compose.yml  # local dev orchestration
├── Makefile            # common dev tasks
├── pyproject.toml      # Python setup
```

## Conventions & code style

### General

* DRY principle: search existing code, check if a similar function or pattern already exists, reuse it when possible
* Focus on clear naming, have non ambiguous variables names
* Add docstrings to public functions and methods, following Google's conventions for Python. Only when it seems relevant, the first line should be followed by an empty line and more explanations
* Break down complex functions into smaller, more manageable pieces of code
* Fix typos and small issues in existing code when you encounter them, even if they are outside the scope of your current task

### HTML and CSS classes

* Consider the style guide in the files `style_guide_emplois.md` before creating or editing HTML templates
* This app must be fully accessible to people with disabilities, following WCAG guidelines and using semantic HTML, and ARIA roles and attributes where appropriate

### Python

* Follow PEP8 formatting, consider ruff rules defined in `pyproject.toml`
* Do not use type hints, since the codebase historically does not use them
* Use `uv` to run Python commands, as per the `Makefile` and `pyproject.toml` setup
* Add comments only when the code is not self-explanatory, or to explain why certain design decisions were made, or to explain the approach used for algorithm-related code, or to explain how some edge cases are handled
* Avoid comments that just restate what the code does

### Django

* Follow standard Django app structure
* Django ORM idioms for queries and migrations
* The platform exposes Django APIs; agents should infer view and serializer patterns from Django REST conventions
* Avoid adding new dependencies unless absolutely necessary, and prefer built-in features when possible
* In templates, always name the 'endblock': {% endblock block_name %}

### Tests

* Prefer pytest, run it through uv: `uv run pytest --exitfirst --create-db`
* Tests under `tests/`, named `test_*.py`
* Keep unit tests isolated from external services, mock underlying services when possible
* Tests should run very fast and be deterministic; avoid relying on external APIs or services in tests
* Mix unit, integration, and end-to-end tests as appropriate, but avoid full end-to-end tests that require the entire stack to be running unless absolutely necessary: test speed matters
* Tests should be concise but exhaustive in covering edge cases
* Use "from http import HTTPStatus" rather than raw status codes
* If a test uses 'assertContains' on a response there is no need to check that the status code of this response is HTTPStatus.OK
* Tests related to a function my_function should be gathered in a class TestMyFunction
* Prefer Django’s request objects instead of parsing URLs with urlparse (e.g. request.GET instead of parse_qs and urlparse)
* Prefer Django helpers (from django.http import QueryDict) for building/modifying query strings
* Prefer parametrizing tests (using pytest features) instead of using for loops or writing separate test functions for similar cases

## You SHOULD follow these steps

1. If unsure, ask questions
2. Suggest an implementation plan before writing code, wait for validation
3. Write a test plan detailing cases that will be covered (happy path, edge cases, validation errors, permissions per role, HTMX swaps, audit trail, responsiveness, accessibility issues), group them logically, and wait for validation
4. TDD approach: write tests before implementation code. Account for critical paths, common edge cases like empty inputs, invalid data types, large datasets, data race conditions, and timezone issues
5. Implement the feature or fix, following the conventions and style guidelines outlined above. Use existing code patterns and utilities where possible to avoid unnecessary complexity. Search the codebase for similar implementations and reuse them when appropriate.
6. After implementation, add tests for any new edge cases that may have been uncovered during development, add unit tests for any new functions or methods, and update existing tests if the behavior of existing functions or methods has changed
7. When necessary, update unrelated features and corresponding tests that may be affected by the initial changes
8. Run specific test modules or classes relevant to the changes being made, iterate until these tests pass
9. Validate linting and formatting with `make fix`
10. Finally, ask to run `make test` to confirm no regressions. In that case, iterate until the full test suite passes without errors

## You SHOULD NOT

* Run `python` or `pytest` without `uv`
* Compromise the integrity of the tests, weaken them, just to make them pass
* Run the full test suite without asking for permission
* Add type hints
* Try to guess environment configs
* Assume JavaScript build systems beyond what’s present (no npm/pnpm unless explicit)
* Rewrite major architectural patterns without direct prompting
* Try to edit the following files, unless absolutely necessary and with explicit validation: `uv.lock`, `pyproject.toml`, `AGENTS.md`,  `.vscode/settings.json`
* Work around the difficulties by adding “if” statements in the tests where there weren’t any before

## Definition of done

* Code follows the established style and conventions of the repo
* All tests related to the modified code pass successfully
* `uv run manage.py makemigrations --check --dry-run` passes without errors, ensuring no pending migrations
* `uv run python manage.py check --deploy` passes without errors
* Documentation is updated if necessary (e.g., docstrings, human docs)
