# Itou

> Plate-forme numérique permettant de simplifier la vie des acteurs de l'inclusion, de renforcer les capacités de coopération, d'innovation et d'accompagnement social et professionnel du secteur et de mieux évaluer l'impact social et les moyens affectés.

## Environnement de développement

### Configuration de l'environnement

    cp config/settings/dev.py.template config/settings/dev.py
    cp envs/dev.env.template envs/dev.env
    cp envs/secrets.env.template envs/secrets.env

Vous pouvez personnaliser la configuration Compose en créant [un fichier `.env`](https://docs.docker.com/compose/env-file/) au même niveau que le fichier `README.md`, puis y configurer les variables d'environnement suivantes :

    DJANGO_PORT_ON_DOCKER_HOST=8000
    POSTGRES_PORT_ON_DOCKER_HOST=5433

### Lancer le serveur de développement

    $ docker-compose -f docker-compose-dev.yml up

    # Ou :
    $ export COMPOSE_FILE=docker-compose-dev.yml
    $ docker-compose up

### Peupler la base de données

    make shell_on_django_container
    django-admin createsuperuser
    django-admin import_cities
    django-admin loaddata itou/fixtures/jobs.json
    django-admin loaddata itou/fixtures/siaes.json
    django-admin loaddata itou/fixtures/test_users.json

### Avant un commit

    make black
    make pylint

## Front-end

> https://getbootstrap.com/docs/4.3/getting-started/introduction/

> https://django-bootstrap4.readthedocs.io/en/latest/index.html

> https://feathericons.com
