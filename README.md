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

    $ make check-code-quality  ## will run black and pylint

## Front-end

> https://getbootstrap.com/docs/4.3/getting-started/introduction/

> https://django-bootstrap4.readthedocs.io/en/latest/index.html

> https://feathericons.com
