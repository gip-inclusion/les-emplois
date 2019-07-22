# Itou

> Plate-forme numérique permettant de simplifier la vie des acteurs de l'inclusion, de renforcer les capacités de coopération, d'innovation et d'accompagnement social et professionnel du secteur et de mieux évaluer l'impact social et les moyens affectés.

## Lancer le serveur de développement

    $ docker-compose -f docker-compose-dev.yml up

    # Ou :
    $ export COMPOSE_FILE=docker-compose-dev.yml
    $ docker-compose up

### Modifier la configuration Compose de développement

Au besoin, vous pouvez créer [un fichier `.env`](https://docs.docker.com/compose/env-file/) au même niveau que le fichier `README.md`, puis y configurer les variables d'environnement suivantes :

    DJANGO_PORT_ON_DOCKER_HOST=8000
    POSTGRES_PORT_ON_DOCKER_HOST=5433

### Créer un administrateur

    make django_admin COMMAND=createsuperuser

### Importer les données des SIAE du département 67

    make django_admin COMMAND=import_siae67
