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

Le reste de la configuration se fait avec des [variables d'environnement](./docs/environment.md).

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

#### Python

`uv` est utilisé pour installer la bonne version de Python et les dépendances
du projet.

Pour l’installer, suivre la documentation officielle
https://docs.astral.sh/uv/getting-started/installation/. Un paquet est
disponible pour la plupart des distributions Linux.

#### Base de données

L’adaptateur Python pour PostgreSQL, [psycopg](https://www.psycopg.org/), a
quelques pré-requis auxquels votre système doit répondre.
https://www.psycopg.org/docs/install.html#runtime-requirements

Par ailleurs, le projet utilise [GDAL](https://gdal.org/index.html), et nécessite
son installation préalable.

Sur MacOS :

```sh
$ brew install gdal
```

Sur Ubuntu :

```sh
$ apt-get install gdal-bin
```

#### Virtualenv

La commande `make` suivante crée un
[`virtualenv`](https://docs.astral.sh/uv/pip/environments/) et installe les
dépendances pour le développement. Elle peut être exécutée régulièrement pour
s’assurer que les dépendances sont bien à jour.

```sh
$ make venv
```

Dans un `virtualenv`, vous pouvez utiliser les commandes Django habituelles
(`./manage.py`) mais également les recettes du [Makefile](./Makefile).

Par défaut l'environment sera stocké dans le répertoire `.venv`. En bash/zsh c'est activé
avec la commande `source .venv/bin/activate` ([doc](https://docs.python.org/3/library/venv.html#how-venvs-work)).

Il est recommandé d'utiliser [direnv](./docs/developing.md#direnv) qui permet l'activation de l'environment automatique.

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

### Accéder au serveur de développement depuis un autre appareil (optionnel)

En supposant que votre serveur ait pour IP `100.1.2.3`, ajoutez cette ligne à votre `.envrc` :

```
export RUNSERVER_DOMAIN=100.1.2.3:8000
```

puis `direnv allow`, `direnv reload` et enfin relancez `make runserver`.

Vous pouvez y accéder à l'adresse http://100.1.2.3:8000/ depuis n'importe quel appareil de votre réseau local.

## Obtenir une base de données de développement

```sh
$ make resetdb
```

## Utiliser les commandes `make` sans connexion à internet

Si vous développez hors ligne et que le fichier de dépendances
(`requirements/dev.txt`) a changé, les commandes `make` vont planter, puisque
lorsque ce fichier change, `uv` va être lancé pour mettre à jour les dépendances
dans le `.venv`.

Pour passer outre, vous pouvez utiliser `make` avec la variable `NETWORK_MODE` :
```sh
$ make NETWORK_MODE=offline resetdb
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
pytest tests/utils/tests.py::TestJSON::test_encoder
```

## Mettre à jour les dépendances Python

La liste des dépendances est consignée dans les fichiers `requirements/*.in`.
Une fois ces fichiers modifiés, les dépendances sont figées avec l’outil
[pip-tools](https://pypi.org/project/pip-tools/). La commande suivante permet
de mettre à jour une dépendance, par exemple `django` :

```sh
$ make compile-deps PIP_COMPILE_OPTIONS="-P django"
```

Si les changements paraissent corrects, ils peuvent être ajoutés à `git` et
*commit*.

## Front-end

- https://getbootstrap.com/docs/4.3/getting-started/introduction/

- https://django-bootstrap5.readthedocs.io/en/latest/index.html

- http://remixicon.com/
