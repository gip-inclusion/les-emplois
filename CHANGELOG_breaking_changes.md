# Journal des changements techniques majeurs
## 2025-01-27

- Utiliser `FORCE_PROCONNECT_LOGIN=False` en local au lieu de `FORCE_IC_LOGIN=False`.

## 2024-11-06

- Mise à jour vers Python 3.12:
    1. Reconstruire le _virtual env_ : `rm -r $VIRTUAL_ENV && make venv`
    2. Mettre à jour ses recettes jetables après avoir `git rebase master`, en
       retirant la variable `CC_CLEVER_PYTHON_VERSION=3.11` de l’environnement
       de l’app sur la console CleverCloud.

## 2024-09-23

- Ajout des variables d'environnement `PRO_CONNECT_*`
  la recette ProConnect peut être utilisée en créant une recette jetable
  et en suivant les indications de la note bitwarden

## 2024-09-22

- Ajout de la variable d'environnement `API_PARTICULIER_TOKEN` pour appeler l'API en local.
La valeur de recette est dans `itou-secrets` > REVIEW-APP.enc.env ou
[sur le dépôt du projet](https://github.com/etalab/siade_staging_data/blob/develop/tokens/default).

## 2024-06-06

- Utilisation de `.envrc`: retrait du hack `.envrc.local`, ce qui permettra de
  recharger l’environnement dès le changement du `.envrc`, et de bénéficier du
  mécanisme de vérification du contenu du fichier.

  Pour migrer : `cp .envrc{.local,}`.

  **Note** : Le fichier `.envrc.local` n’est plus utile. Cependant, attendre
  quelques semaines avant de le supprimer permet d’éviter de perdre le contenu
  du `.envrc` lorsqu’on change vers une branche dont le `.envrc` était suivi
  par `git`.

## 2024-05-28

- Le fichier `.env` devient optionnel (et probablement inutile). Si vous
  utilisiez dotenv (fichier `.env`), migrez avec :
  ```sh
  $ echo dotenv >> .envrc.local
  ```

## 2024-04-08
- Suppression de la commande `make deploy_prod`, les PRs arrivant sur la branche master sont immédiatement déployées par CleverCloud.

## 2024-03-14
- Définition d’`API_BAN_BASE_URL` requise, utiliser la valeur du [`.env.template`](./.env.template).

## 2024-02-14
- Redis devient un composant requis de l’infrastructure de dev, et la prod l’utilise pour le cache Django. Pour mettre à jour son environnement de développement :

    1. Mettre à jour son `.env` à partir du `.env.template`
    2. `docker compose up redis --detach`

## 2024-01-31
- Suppression de `CLEVER_TOKEN` et `CLEVER_SECRET`.

## 2023-11-16
- Renommage SIAE en Company dans tout le code non spécifique à l'IAE. De nombreux modèles et champs ont été renommés (avec migrations et renommage en base de données) et des urls ont changé. Voir les PR commençant par « Renommage Siae ».

## 2023-12-18
- Déplacement du _virtual env_ utilisé par le container de `.venv` à `.venv-docker`.
- Ajout de ShellCheck à la configuration de pre-commit.
