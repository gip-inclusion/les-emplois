# Itou - Les emplois de l'inclusion

> Les emplois de l'inclusion est un service numérique de délivrance des PASS IAE
> et de mise en relation d'employeurs solidaires avec des candidats éloignés de
> l'emploi par le biais de tiers (prescripteurs habilités, orienteurs) ou en
> autoprescription.

# Environnement de développement

## Définition des variables d'environnement

Les valeurs par défaut de `dev.py` permettent de lancer un environnement fonctionnel.

Cependant, il est recommandé d'en prendre connaissance pour noter par exemple
que les emails ne sont pas réellement envoyés mais que leur contenu est
simplement écrit dans la sortie standard.

Le reste de la configuration se fait avec des variables d'environnement.

Celles concernant notre hébergeur CleverCloud sont définis au niveau du déploiement et
de l'app CleverCloud tandis que les autres paramètres applicatifs indépendants du PaaS
sont définis dans le projet `itou-secrets`.

## Installation

L’application est développée avec [Django](https://www.djangoproject.com/), la
base de données est gérée par [PostgreSQL](https://www.postgresql.org/).

_Les instructions ci-dessous vous permettront d’obtenir un environnement de
développement pratique à utiliser au quotidien. Pour obtenir un environnement
fonctionnel très rapidement, mais moins ouvert au développement, suivre les
instructions [containerization](./docs/Docker.md)._

### Docker

Vous devez disposer sur votre machine du service `Docker` et de l'outil `Docker
Compose`. Si ce n'est pas encore le cas :

- [Installer Docker](https://docs.docker.com/engine/install/)
- [Installer Docker Compose](https://docs.docker.com/compose/install/)

Vous pouvez également personnaliser la configuration de Docker Compose en
créant [un fichier `.env`](https://docs.docker.com/compose/env-file/) à partir
d'une copie du fichier racine `.env.template`. Le fichier `.env` doit être au
même niveau que le fichier `README.md`.

### Base de données

L’adaptateur Python pour PostgreSQL, [psycopg](https://www.psycopg.org/), a
quelques pré-requis auxquels votre système doit répondre.
https://www.psycopg.org/docs/install.html#runtime-requirements

### Dépendences Python (`virtualenv`)

La commande `make` suivante crée un
[`virtualenv`](https://docs.python.org/3/library/venv.html) et installe les
dépendances pour le développement. Elle peut être exécutée régulièrement pour
s’assurer que les dépendances sont bien à jour.

```sh
$ make venv
```

Dans un `virtualenv`, vous pouvez utiliser les commandes Django habituelles
(`./manage.py`) mais également les recettes du [Makefile](./Makefile).

### Accéder au serveur de développement

Démarrer le serveur de développement avec la commande :

```sh
$ make runserver
```

Vous pouvez y accéder à l'adresse http://localhost:8000/.

### Peupler la base de données

```sh
$ make populate_db
```

### Charger une base de données de production

Inspirez-vous de la suite de commandes suivante :

```sh
$ rclone copy --max-age 24h --progress emplois:/encrypted-backups ./backups
$ pg_restore --jobs=4 --no-owner backups/backup.dump
$ python manage.py set_fake_passwords
$ python manage.py shell --command 'from itou.users.models import User; print(User.objects.update(identity_provider="DJANGO"))'
```

Rendez-vous sur la doc de
[itou-backups](https://github.com/betagouv/itou-backups) pour plus d’infos.

## Qualité de code

```sh
make quality
```

### Automatiquement avant chaque commit

[Pre-commit](https://pre-commit.com) est un outil qui gère des _hooks_ de
pre-commit Git.

Cela remplace les [configurations
individuelles](https://git-scm.com/book/en/v2/Customizing-Git-Git-Hooks) par un
fichier de configuration présent dans le projet.

```sh
$ pre-commit install
```

## Lancer les tests

Le projet utilise [pytest](https://docs.pytest.org/).

Lancer la suite complète, comme sur la CI :
```sh
make test
```

Lancer un test en particulier :
```sh
pytest itou/utils/tests.py::JSONTest::test_encoder
```

### MacOS

Les Mac utilisant l’architecture M1 ont besoin d’émuler le jeu d’instructions
`amd64`, ce qui rend l’exécution de la suite de test plus longue et peut
rapidement rencontrer les sécurités (_timeout_) configurées.

Pour éviter ces erreurs,
[pytest-timeout](https://github.com/pytest-dev/pytest-timeout#usage) propose
deux options :

1. Définir la variable d’environnement `PYTEST_TIMEOUT`, par exemple à une
   valeur de `60` secondes.
2. Utiliser `--timeout` lors de l’invocation de `pytest` :
    ```sh
    pytest --timeout 60
    ```

## Mettre à jour les dépendances Python

La liste des dépendances est consignée dans les fichiers `requirements/*.in`.
Une fois ces fichiers modifiés, les dépendances sont figées avec l’outil
[pip-tools](https://pypi.org/project/pip-tools/). La commande suivante permet
de mettre à jour une dépendance, par exemple `flake8` :

```sh
$ PIP_COMPILE_OPTIONS="-P flake8" make compile-deps
```

Si les changements paraissent corrects, ils peuvent être ajoutés à `git` et
*commit*.

## Front-end

- https://getbootstrap.com/docs/4.3/getting-started/introduction/

- https://django-bootstrap4.readthedocs.io/en/latest/index.html

- http://remixicon.com/
