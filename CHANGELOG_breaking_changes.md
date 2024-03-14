# Journal des changements techniques majeurs

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
