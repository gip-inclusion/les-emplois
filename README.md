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

    # Équivalent de :
    $ docker-compose -f docker-compose-dev.yml up

Ou pour utiliser [un débogueur interactif](https://github.com/docker/compose/issues/4677#issuecomment-320804194) type `ipdb` :

    $ docker-compose -f docker-compose-dev.yml run --service-ports django

### Peupler la base de données

    $ make populate_db

### Créer un compte admin

    $ make shell_on_django_container
    $ django-admin createsuperuser

### Avant un commit

    $ make style  # Will run black and isort.

Ou utilisez un *pre-commit git hook* que vous pouvez mettre en place de cette manière :

    $ make setup_git_pre_commit_hook

## Données de test

Voir notre [documentation interne](https://team.inclusion.beta.gouv.fr/les-procedures/recette-test).

## Front-end

> https://getbootstrap.com/docs/4.3/getting-started/introduction/

> https://django-bootstrap4.readthedocs.io/en/latest/index.html

> https://feathericons.com
