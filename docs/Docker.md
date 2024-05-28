# Environnement de développement dans un Docker

Au lieu d’installer l’application sur votre système, il est possible de
l’embarquer dans un container Docker, qui vous permettra de faire fonctionner
le code plus facilement.

## Démarrage

```sh
$ docker compose --profile=django up
```

## Utilisation

### Commandes de gestion

Se placer dans le container `itou_django` avec :

```sh
make shell_on_django_container
```

Dans cet interpréteur, il est possible d’utiliser les commandes `python
manage.py <…>` et `make <…>`.

### Gestion de la base PostgreSQL

Se placer dans le container `itou_postgres` avec :

```sh
make shell_on_postgres_container
```

Dans cet interpréteur, les utilitaires PostgreSQL tels que `psql`, `pg_dump`,
`pg_restore` sont disponibles.

### Copier des fichiers

Le code applicatif est [monté](https://docs.docker.com/storage/bind-mounts/)
directement dans le docker, ce qui permet de refléter les modifications du code
source effectuées sur l’hôte dans le container. Le serveur de développement se
recharge automatiquement lors des changements.

Pour transmettre d’autres fichiers, utiliser la commande [`docker
cp`](https://docs.docker.com/engine/reference/commandline/cp/) depuis la
machine hôte :

```sh
$ docker cp backups/2023-09-12.dump itou_postgres:/backups/
```

## Mise à jour des dépendances Python

**Dans le container `itou_django`**, lancer la commande :
```sh
make venv
```

## Effacer l'ancienne base de données

Pour supprimer la base de données dans Docker vous devez supprimer les volumes
de l'image docker, en exécutant la commande suivante :

```sh
docker compose --profile=django down --volumes
```

## Débogueur

Pour utiliser [un débogueur
interactif](https://github.com/docker/compose/issues/4677#issuecomment-320804194)
type `ipdb` :

```sh
$ docker compose --profile=django run --service-ports django
```

## Variables d’environnement

Les variables d’environnement suivantes vous permettent de personnaliser le
fonctionnement du `docker compose`. Vous pouvez les enregistrer dans un fichier
`.env` à la racine du projet (dans le même répertoire que le fichier
[README.md](../README.md)).

```sh
DJANGO_PORT_ON_DOCKER_HOST=8000
POSTGRES_PORT_ON_DOCKER_HOST=5432
MINIO_PORT_ON_DOCKER_HOST=9000
MINIO_ADMIN_PORT_ON_DOCKER_HOST=9001

# Needed for the ./scripts/restore_latest_backup.sh script.
# Path to your local itou-backups repository.
PATH_TO_ITOU_BACKUPS=set_me
```
