# Itou

> Plate-forme numérique permettant de simplifier la vie des acteurs de l'inclusion, de renforcer les capacités de coopération, d'innovation et d'accompagnement social et professionnel du secteur et de mieux évaluer l'impact social et les moyens affectés.

## Créer un fichier `envs/secrets.env`

```
API_INSEE_KEY=set_it
API_INSEE_SECRET=set_it
```

## Lancer le serveur de développement

    $ docker-compose -f docker-compose-dev.yml up

    # Ou :
    $ export COMPOSE_FILE=docker-compose-dev.yml
    $ docker-compose up

### Modifier la configuration Compose de développement

Au besoin, vous pouvez créer [un fichier `.env`](https://docs.docker.com/compose/env-file/) au même niveau que le fichier `README.md`, puis y configurer les variables d'environnement suivantes :

    DJANGO_PORT_ON_DOCKER_HOST=8000
    POSTGRES_PORT_ON_DOCKER_HOST=5433

### Peupler la base de données

    make shell_on_django_container
    django-admin createsuperuser
    django-admin loaddata itou/fixtures/siae.json

### Front-end style guide

> https://turretcss.com/demo/
