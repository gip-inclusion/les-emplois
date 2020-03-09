# Itou

> Plateforme numérique permettant de simplifier la vie des acteurs de l'inclusion, de renforcer les capacités de coopération, d'innovation et d'accompagnement social et professionnel du secteur et de mieux évaluer l'impact social et les moyens affectés.

## Environnement de développement

### Configuration de l'environnement

    cp config/settings/dev.py.template config/settings/dev.py
    cp envs/dev.env.template envs/dev.env
    cp envs/secrets.env.template envs/secrets.env

Vous pouvez personnaliser la configuration Compose en créant [un fichier `.env`](https://docs.docker.com/compose/env-file/) au même niveau que le fichier `README.md`, puis y configurer les variables d'environnement suivantes :

    DJANGO_PORT_ON_DOCKER_HOST=8000
    POSTGRES_PORT_ON_DOCKER_HOST=5433

### Lancer le serveur de développement

    $ make run

### Peupler la base de données

    $ make populate_db

The following users will be created with the password `password` (*sic*):

- `admin@test.com`
- `job@test.com`
- `prescriber@test.com`
- `siae@test.com`
- `prescriber-solo@test.com`

### Créer un compte admin

    $ make shell_on_django_container
    $ django-admin createsuperuser

### Avant un commit

    $ make check_code_quality  # Will run isort, black, flake8 and pylint.

Even better, use a pre-commit git hook, simply set it up this way:

    $ make setup_git_pre_commit_hook

Note that pylint is much slower than the three other tools. For this reason,
our pre-commit hook does not run it. But you can still manually run it
via `make pylint` or via `make check_code_quality`.

## Front-end

> https://getbootstrap.com/docs/4.3/getting-started/introduction/

> https://django-bootstrap4.readthedocs.io/en/latest/index.html

> https://feathericons.com
