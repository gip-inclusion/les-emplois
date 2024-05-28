# Itou - Les emplois de l'inclusion

> Les emplois de l'inclusion est un service numérique de délivrance des PASS IAE
> et de mise en relation d'employeurs inclusifs avec des candidats éloignés de
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
base de données est gérée par [PostgreSQL](https://www.postgresql.org/) et le
stockage objet type *S3* [MinIO](https://min.io/).

_Les instructions ci-dessous vous permettront d’obtenir un environnement de
développement pratique à utiliser au quotidien. Pour obtenir un environnement
fonctionnel très rapidement, mais moins ouvert au développement, suivre les
instructions [containerization](./docs/Docker.md)._

### Services nécessaires

Les dépendances (base de données PostgreSQL et le stockage objet type *S3*)
sont rendues disponibles par [Docker](https://docs.docker.com/) et
[Docker Compose](https://docs.docker.com/compose/).

- [Installer Docker](https://docs.docker.com/engine/install/)
- [Installer Docker Compose](https://docs.docker.com/compose/install/)

Démarrez les dépendances de développement avec la commande :
```sh
docker compose up
```

**Note** : Vous pouvez personnaliser la configuration des dépendances gérées
par Docker Compose en créant [un fichier
`.env`](https://docs.docker.com/compose/env-file/) au même niveau que le
fichier `README.md`.

### Dépendances Python

#### Base de données

L’adaptateur Python pour PostgreSQL, [psycopg](https://www.psycopg.org/), a
quelques pré-requis auxquels votre système doit répondre.
https://www.psycopg.org/docs/install.html#runtime-requirements

#### Virtualenv

La commande `make` suivante crée un
[`virtualenv`](https://docs.python.org/3/library/venv.html) et installe les
dépendances pour le développement. Elle peut être exécutée régulièrement pour
s’assurer que les dépendances sont bien à jour.

```sh
$ make venv
```

Dans un `virtualenv`, vous pouvez utiliser les commandes Django habituelles
(`./manage.py`) mais également les recettes du [Makefile](./Makefile).

### Création des *buckets S3*

Les fichiers téléversés sont enregistrés dans un stockage objet type *S3*. En
local, le service est rendu par [MinIO](https://min.io/). Sa console
d’administration est disponible à l’adresse http://localhost:9001/.

Login : `minioadmin`
Password : `minioadmin`

Afin de créer les *buckets* nécessaires au développement et aux tests, lancer la commande :
```sh
$ make buckets
```

## Accéder au serveur de développement

Démarrer le serveur de développement avec la commande :

```sh
$ make runserver
```

Vous pouvez y accéder à l'adresse http://localhost:8000/.

## Créer le schéma de base de données

```sh
$ python manage.py migrate
```

## Peupler la base de données

```sh
$ make populate_db
```

## Charger une base de données de production

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

- https://django-bootstrap5.readthedocs.io/en/latest/index.html

- http://remixicon.com/
