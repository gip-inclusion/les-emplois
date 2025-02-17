# Développement local

## direnv

Nous conseillons d'installer le minuscule utilitaire [direnv](https://direnv.net/) pour charger et
décharger automatiquement des variables d'environnement à l'entrée dans un
répertoire.

Une fois muni de cet outil (avec `apt`, `brew` ou autre, et sans oublier de
[mettre le hook](https://direnv.net/#basic-installation)) il suffit de créer un
fichier de variables d'environnement local:

```sh
cat <<EOF >.envrc
# Activate the virtual environment
source .venv/bin/activate

# Setting environment variables for the application
export DJANGO_DEBUG=True
export DJANGO_LOG_LEVEL=WARNING
export SQL_LOG_LEVEL=INFO
export DJANGO_SECRET_KEY=foobar

# For psql
export PGHOST=localhost
export PGUSER=postgres
export PGPASSWORD=password
export PGDATABASE=itou
EOF
```

La [liste des variables d’environnement fréquemment
utilisées](./environment.md) est disponible dans cette documentation.

Une fois le fichier `.envrc` saisit, il suffit de l'autoriser dans `direnv`:

```sh
direnv allow .envrc
```

Et c’est bon, vos variables seront chargées à chaque entrée dans le dossier et
retirées en sortant.

```sh
psql  # connects directly to the itou database
./manage.py xxxx  # any commands work immediately
```

## Compte superutilisateur local

Parmi les comptes créées en peuplant la base de données pour le développement en local se trouve un compte superutilisateur :

- **nom d'utilisateur** : admin
- **email** : admin@test.com
- **mot de passe** : password

Ces identifiants sont utilisables pour se connecter à la console d'administration de Django en local : [http://localhost:8000/admin](http://localhost:8000/admin).
