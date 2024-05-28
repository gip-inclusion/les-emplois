# Variables d’environnement

L’application devrait fonctionner sans configuration particulière. Les
variables d’environnement suivantes permettent d’adapter l’application à votre
environnement, et de paramétrer des composants optionnels du système.

L’inspection des [settings Django](../config/settings/) permet d’avoir la
référence complète des variables d’environnement. Les variables souvent
utilisées sont recensées dans ce document.

## Définir les variables d’environnement

Dans votre environnement de développement, l’utilisation de
[direnv](./direnv.md) est recommandée.

En production, un fichier `.env` est généré au déploiement et chargé avec
l’utilitaire [`dotenv`](https://pypi.org/project/python-dotenv/). Cette
configuration est moins flexible que direnv, car les variables d’environnement
ne sont pas disponibles pour votre shell, ce qui empêche le chargement
automatique de l’environnement virtuel, ou de lancer `psql` sans spécifier les
arguments pour se connecter à la base de données.

## Variables de confort

### PostgreSQL

Les variables suivantes permet d’accéder à la base de données définie dans le
[docker-compose.yml](../docker-compose.yml) simplement avec la commande `psql`.

```bash
export PGDATABASE=itou
export PGHOST=localhost
export PGUSER=postgres
export PGPASSWORD=password
```

### CleverCloud

La [_CLI_ CleverCloud](https://developers.clever-cloud.com/doc/cli/) peut
récupérer les informations de connexion depuis l’environnemnt :

```bash
export CLEVER_TOKEN=VOTRE_TOKEN
export CLEVER_SECRET=VOTRE_SECRET
```

## Systèmes externes

### Inclusion Connect

`FORCE_IC_LOGIN` : Obliger les employeurs et prescripteurs à utiliser
[Inclusion Connect](https://github.com/gip-inclusion/inclusion-connect).

D’autres variables d’environnement permettent de configurer la connexion avec
Inclusion Connect, elles sont préfixées par `INCLUSION_CONNECT_`.

#### Mailjet

#### `API_MAILJET_KEY_APP` & `API_MAILJET_SECRET_APP`

Identifiants Mailjet de l’applicatif, utilisé lors de l’envoi d’emails.

#### `API_MAILJET_KEY_PRINCIPAL` & `API_MAILJET_SECRET_PRINCIPAL`

Identifiants Mailjet du compte principal, utilisé pour alimenter les listes de
diffusion pour les campagnes Mailjet.

### `MATOMO_BASE_URL`

Connexion à l’instance Matomo du GIP de l’inclusion. Le site par défaut dans
l’environnement de développement est un site dédié aux expérimentations.

### `REDIS_URL`

Connexion à Redis, au format `redis://<host>:<port>`.
