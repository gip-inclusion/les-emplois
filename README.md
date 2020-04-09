# Itou

> Plateforme numérique permettant de simplifier la vie des acteurs de l'inclusion, de renforcer les capacités de coopération, d'innovation et d'accompagnement social et professionnel du secteur et de mieux évaluer l'impact social et les moyens affectés.

## Données de test

### Utilisateurs

| Id | Prénom     |    Nom    |                                        E-mail | Organisation(s)                              | Créé par     | Description                                                    |
|----|------------|:---------:|----------------------------------------------:|----------------------------------------------|--------------|----------------------------------------------------------------|
| 1  |            |           |                                admin@test.com |                                              |              | Administrateur Django                                          |
| 2  | Jacques    |   Henry   |             contact+de@inclusion.beta.gouv.fr |                                              |              | Demandeur d'emploi                                             |
| 3  | Sylvie     |   Martin  |       contact+de-proxy@inclusion.beta.gouv.fr |                                              | André Dufour | Demandeur d'emploi - compte créé par un prescripteur habilité. |
| 4  | André      | Dufour    | contact+prescripteur@inclusion.beta.gouv.fr   | PE Arles, PE 93                               |              | Prescripteur habilité administrateur de ses deux structures.   |
| 5  | Olivier    | Dupuy     | contact+orienteur@inclusion.beta.gouv.fr      | Association La Belle Verte                   |              | Prescripteur non habilité, administrateur de sa structure.     |
| 6  | Emmanuelle | Dubreuil  | contact+orienteur-solo@inclusion.beta.gouv.fr |                                              |              | Prescripteur non habilité                                      |
| 7  | Daphnée    | Delavigne | contact+etti@inclusion.beta.gouv.fr           | ETTI Une nouvelle chance, EI Garage Martinet |              | Employeur administrateur d'une ETTI et membre d'une EI.        |
| 8  | Victor     | Lacoste   | contact+ei@inclusion.beta.gouv.fr             | EI Garage Martinet, ETTI Une nouvelle chance |              | Employeur administrateur d'une EI et membre d'une ETTI.        |

Tous les utilisateurs ont le mot de passe `password`.

### Organisations

| Nom                        | Adresse                                      | Fiches de poste                                                   | Type                              |
|----------------------------|----------------------------------------------|-------------------------------------------------------------------|-----------------------------------|
| Association La Belle Verte | 10 place de l'Eglise, 13113 Lamanon          |                                                                   | Organisation prescripteur (autre) |
| EI Garage Martinet         | Route d'Altaves, 13103 Saint-Étienne-du-Grès | - Chef de garage - Mécanicien / Mécanicienne de garage automobile | EI |
| ETTI Une nouvelle chance   | 14 Avenue de la Plaine, 30300 Beaucaire      | - Figurant / Figurante                                            | ETTI                              |

### Candidatures

Deux candidatures (une en attente, l'autre à l'étude) pour l'organisation ETTI Une nouvelle chance :
- une en auto-prescription,
- l'autre provenant d'un DE.


## Environnement de développement

### Configuration de l'environnement

    cp config/settings/dev.py.template config/settings/dev.py
    cp envs/dev.env.template envs/dev.env
    cp envs/secrets.env.template envs/secrets.env

Vous pouvez personnaliser la configuration Compose en créant [un fichier `.env`](https://docs.docker.com/compose/env-file/) au même niveau que le fichier `README.md`, puis y configurer les variables d'environnement suivantes :

    DJANGO_PORT_ON_DOCKER_HOST=8000
    POSTGRES_PORT_ON_DOCKER_HOST=5433

### Lancer le serveur de développement

    $ make run

    # Équivalent de :
    $ docker-compose -f docker-compose-dev.yml up

Ou pour utiliser [un débogueur interactif](https://github.com/docker/compose/issues/4677#issuecomment-320804194) type `ipdb` :

    $ docker-compose -f docker-compose-dev.yml run --service-ports django

### Peupler la base de données

    $ make populate_db


### Créer un compte admin

    $ make shell_on_django_container
    $ django-admin createsuperuser

### Avant un commit

    $ make style  # Will run black and isort.

Ou utilisez un *pre-commit git hook* que vous pouvez mettre en place de cette manière :

    $ make setup_git_pre_commit_hook

## Front-end

> https://getbootstrap.com/docs/4.3/getting-started/introduction/

> https://django-bootstrap4.readthedocs.io/en/latest/index.html

> https://feathericons.com
