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


## macOS et puces Apple Silicon

Si la librairie GDAL a été installée avec [brew](https://formulae.brew.sh/formula/gdal) et que vous tentez de lancer l'application Django en local, l'erreur suivante peut se produire :
```
django.core.exceptions.ImproperlyConfigured: Could not find the GDAL library...
```
Celle-ci indique que Django ne trouve pas les binaires de la librairie.

Les chemins des binaires des libraries GDAL et GEOS peuvent être définis grâce aux variables d'environnement `GDAL_LIBRARY_PATH` et `GEOS_LIBRARY_PATH`.
Il est possible de définir celles-ci via le fichier `.envrc` si vous utilisez direnv :
```sh
export GDAL_LIBRARY_PATH="$(brew --prefix gdal)/lib/libgdal.dylib"
export GEOS_LIBRARY_PATH="$(brew --prefix geos)/lib/libgeos_c.dylib"
```
