# Itou - Les emplois de l'inclusion

> Les emplois de l'inclusion est un service numérique de délivrance des PASS IAE
> et de mise en relation d'employeurs solidaires avec des candidats éloignés de
> l'emploi par le biais de tiers (prescripteurs habilités, orienteurs) ou en
> autoprescription.

## Environnement de développement

### Définition des variables d'environnement

Commencez par copier le gabarit du fichier de configuration Django prévu pour le
développement :

    cp config/settings/dev.py.template config/settings/dev.py

Les valeurs par défaut de `dev.py` permettent de lancer un environnement fonctionnel.

Cependant, il est recommandé d'en prendre connaissance pour noter par exemple
que les emails ne sont pas réellement envoyés mais que leur contenu est
simplement écrit dans la sortie standard.

Le reste de la configuration se fait avec des variables d'environnement. Deux
fichiers de configuration, `dev.env` et `secrets.env` doivent être créés :

    cp envs/dev.env.template envs/dev.env
    cp envs/secrets.env.template envs/secrets.env

Le fichier `dev.env` contient les variables d'environnement dont la valeur peut
être partagée et pour lesquelles la valeur définie par défaut est viable pour un
environnement de développement.

À l'inverse, le fichier `secrets.env` regroupe les variables propres à votre
environnement et par nature « sensible ». Ces variables n'ont donc pas de valeur
par défaut viable et doivent donc être configurées par vos soins.

### Développement avec Docker

Vous devez disposer sur votre machine d'un démon `Docker` et de l'outil `Docker
Compose`. Si ce n'est pas encore le cas :

- [Installer Docker](https://docs.docker.com/engine/install/)
- [Installer Docker Compose](https://docs.docker.com/compose/install/)

Vous pouvez également personnaliser la configuration Compose en créant [un
fichier `.env`](https://docs.docker.com/compose/env-file/) au même niveau que le
fichier `README.md`, puis y configurer les variables d'environnement suivantes :

    DJANGO_PORT_ON_DOCKER_HOST=8080
    POSTGRES_PORT_ON_DOCKER_HOST=5433

### Développement dans un Virtualenv

Créez votre environnement avec vos commandes habituelles, par exemple
`python -m venv <votrevenv itou>` ou `mkvirtualenv itou`.

Pour charger automatiquement les variables d'environnement à l'activation de
votre Virtualenv, ajoutez les lignes suivantes au script `bin/activate` du venv
en adaptant le chemin :

    set -a
    . $HOME/itou/envs/dev.env
    . $HOME/itou/envs/secrets.env
    set +a

Les dépendances peuvent êtres installées via `pip install -r requirements/dev.txt`.

### Lancer le serveur de développement

Avec Docker :

    $ make run

    # Équivalent de :
    $ docker-compose up

Ou pour utiliser [un débogueur interactif](https://github.com/docker/compose/issues/4677#issuecomment-320804194) type `ipdb` :

    $ docker-compose run --service-ports django

Une fois votre serveur de développement lancé, vous pouvez accéder au frontend à
l'adresse http://localhost:8080/.

Dans un Virtualenv, vous pouvez utiliser les commandes Django habituelles
(`./manage.py`), des commandes spécifiques au Virtualenv sont disponibles dans
le Makefile. Elles sont suffixées par `_venv`.

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

- https://getbootstrap.com/docs/4.3/getting-started/introduction/

- https://django-bootstrap4.readthedocs.io/en/latest/index.html

- https://feathericons.com
