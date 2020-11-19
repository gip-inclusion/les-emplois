# Journal des modifications (*Changelog*)

Toutes les modifications notables apportées au projet seront documentées dans ce fichier.

Le format est basé sur [Tenez un Changelog](https://keepachangelog.com/en/1.0.0/).

*Ce projet n'adhère plus au [*Semantic Versioning*](https://semver.org/spec/v2.0.0.html) depuis la version 2*.

## [7] - 2020-11-19

### Ajouté
- Ouverture région Normandie
- Ajout d'un lien vers le décret concernant les critères d’eligibilité
- Ajout d'un message d'information dans la liste des candidatures en attente et dans l'email de nouvelle candidature
- Ouverture région Pays de la Loire
- Inscription possible de plusieurs structures ayant un même SIRET mais des types différents
- Un administrateur de structure peut gérer ses collaborateurs
- Possibilité d'avoir plusieurs administrateurs par structure
- Ajout du lien de la place de marché dans le tableau de bord de certaines SIAE
- Correction d'une erreur d'affichage sur Microsoft Edge et Internet Explorer
- Ajout du type de structure sur le tableau de bord et dans la liste de sélection multi-structure

### Modifié
- Modification de la couleur du bouton lors d'une demande de PASS IAE
- Filtrage des liens internes Pôle emploi pour les CV (adresses locales)
- Modification des informations d'inscription d'un employeur solidaire
- Simplification du code d'ouverture d'une région
- Modification du champ "enseigne" dans la fiche SIAE
- La géolocalisation ne tient plus compte du complément d'adresse (baisse de qualité du score) 

## [6] - 2020-11-05

### Ajouté
- Ouverture de la France d'outre-mer

### Modifié
- Retrait de la restriction des 24h pour les employeurs avant de pouvoir embaucher à nouveau
- Correction d'une erreur de geocoding qui bloquait le parcours d'inscription des prescripteurs à la saisie du SIRET

## [5] - 2020-10-23

### Ajouté
- Un prescripteur peut maintenant travailler sur plusieurs organisations
- Le code SAFIR est maintenant visible dans l'interface utilisateur
- Admin :
    - Ajout de la possibilité de valider une habilitation préalablement refusée
    - Ajout de la possibilité de saisir ou de modifier le code SAFIR d'une agence Pôle emploi
- Ouverture de la région Bretagne
- Import des structures GEIQ
- Intégration du lien enquête employeur dans la plateforme

### Modifié
- Correction de la limite minimum de 16 ans du champ date de naissance de divers formulaires
- Correction des données des recettes jetables
- Correction des données (fixtures) de la démo
- Correction en démo du compte EI qui pointait vers une ETTI
- Remplacement du statut "Candidature annulée" par "Embauche annulée"
- Amélioration wording pour une structure qui tente de s'inscrire et qui est non référencée

## [4] - 2020-10-08

### Ajouté
- Parcours de bienvenue pour les nouveaux utilisateurs
- Import des agréments Pôle emploi de Septembre 2020
- Ajout de la possibilité de refuser les PASS IAE dans l'admin
- Nouveau type "Dispositif conventionné par le conseil départemental pour le suivi BRSA" pour les organisations de prescripteurs (visible uniquement dans l'admin)
- Prolongation +3mois COVID pour les agréments existants préalablement côté PE et délivrés par Itou
- Explication du classement des résultats d'une recherche de SIAE 
- Rafraîchissement journalier des données Metabase
- Stockage des conventions et des annexes financières en provenance de l'ASP
- Ajout d'un lien vers un formulaire Typeform destiné au support pour signaler un problème d'inscription d'une SIAE qui ne trouverait pas sa structure
- Améliorations de l'accessibilité :
    - Ajout de `aria-label` aux liens "Forum" et "Documentation"
    - Ajout de `<label>` aux champs de recherche du moteur de recherche (visibles uniquement aux lecteurs d'écrans)
    - Ajout de texte alternatif au logo de géolocalisation du moteur de recherche
    - Ajout de `aria-label` aux boutons "Postuler"
    - Ajout d'un logo d'ouverture vers un nouvel onglet pour les liens externe du footer
    - Ajout de `aria-label` au bouton "Se connecter avec Pôle emploi"

### Modifié
- Demande d'une confirmation avant une annulation de candidature
- Correction d'un bug Mailjet pour des emails avec plus de 50 destinataires non envoyés
- Mise à jour de Django en version 3.1.2
- Affichage de l'email saisi sur l'écran de confirmation de réinitialisation d'un mot de passe
- Correction d'une erreur 500 quand un DE visitait une page réservée aux SIAE
- Apport d'une précision sur le critère BRSA en ajoutant "socle" à coté
- Signalement que l'absence d'identifiant Pôle emploi ralentit le traitement et la délivrance d'un PASS IAE
- Affichage d'un texte d'aide et d'un message d'erreur pour dire à un employeur qu'une embauche dans le passé est impossible

### Supprimé
- Fin de l'expérimentation de l'affichage d'une carte dans les résultats d'une recherche

## [3] - 2020-09-24

### Ajouté
- Déploiement - Nouvelle Aquitaine (22 septembre)
- Déploiement - Centre Val de Loire (21 septembre)
- Possibilité de joindre un CV à une candidature
- Accès "Statistiques et pilotage" avec des sections accessibles sur privilège :
    - "Voir les statistiques avancées"
    - "Voir les données sur mon territoire "
- 4 nouvelles villes dans le moteur de recherche :
    - Miquelon-Langlade (975)
    - Saint-Pierre (974)
    - Saint-Barthélemy (971)
    - Saint-Martin (971)
- Possibilité pour tous les prescripteurs de modifier l'adresse postale de leur organisation
- Ajout d'un filtre dans l'admin des utilisateurs pour pouvoir distinguer les demandeurs d'emploi autonomes

### Modifié
- Refactoring du script d'import des SIAE en préparation du chantier "conventionnement"
- Correction d'un bug qui permettait à un utilisateur d'être membre plusieurs fois de la même organisation
- Précision dans les critères d'éligibilité sur le Niveau d'étude III pour confirmer qu'il s'agit de la nouvelle nomenclature CAP, BEP ou infra
- Nouvelles règles métier du diagnostic d'éligibilité :
    - un diagnostic est valide s'il existe un PASS IAE ou un AGREMENT PE valide
    - un diagnostic réalisé par une SIAE n'est visible que par elle
    - un diagnostic réalisé par un prescripteur habilité a toujours la priorité même si un diagnostic réalisé par une SIAE existe au préalable
- Nouveau look du pied de page avec une couleur moins sombre
- Utilisation du wording "extranet IAE 2.0 de l'ASP" plutôt que "ASP"
- Mise à niveau de l'API Mailjet pour utiliser la version 3.1
- On affiche plus de point (`.`) juste après l'e-mail dans le message qui stipule qu'une confirmation d'e-mail a été envoyé
- Reformulation du bouton "Se connecter" pour "S'inscrire | Se connecter"
- Reformulation des boutons :
    - "Je ne veux pas l'embaucher" en "Décliner la candidature"
    - "Je veux l'embaucher plus tard" en "Mettre en liste d'attente"
- Interdiction de créer un compte candidat avec un e-mail en `@pole-emploi.fr`
- Dans le tableau de bord d'une SIAE, on n'affiche plus les liens "_Candidatures à traiter_" ou "_Candidatures acceptées et embauches prévues_" ou "_Candidatures refusées/annulées_" si aucune candidature ne rentre dans ces catégories
- Déplacement du lien "Mot de passe oublié"
- Correction d'un bug dans l'admin utilisateur où le lien vers une SIAE n'apparaissait pas
- La modale "Obtention d'un PASS IAE" n'apparaît plus pour les entreprises non soumises aux règles de l'éligibilité
- Correction d'une erreur 500 dans l'admin des organisations de prescripteurs quand un objet n'existait pas
- Optimisation du nombre de requêtes dans l'admin des utilisateurs

## [2] - 2020-09-10

### Ajouté
- Mise en place d'une architecture de traitement asynchrone des tâches (avec Huey et Redis)
- Import SIAE ASP avec 23 nouvelles structures et 4 structures réactivées
- Ajout du champ SIRET dans le formulaire de modification des organisations de prescripteurs
- Ajout du type EITI avec ses 5 structures
- Limitation de la création d'antennes au même type et seulement dans les départements autorisés pour ce type (France entière ETTI, départements ouverts pour les autres)
- Simplification de l'inscription des SIAE, on ne demande plus que le SIREN

### Modifié
- Remplacement du logo CIE par le logo du Ministère dans les attestations PDF (exemple)
- Admin
    - le SIRET des organisations de prescripteurs devient unique
    - fix pour une erreur 500 quand l'email d'un utilisateur existe déjà
    - élargissement des champs de recherche
        - organisations de prescripteurs : recherche aussi dans "ville", "département", "code postal", "adresse"
        - candidature : recherche aussi dans "émetteur de la candidature" (e-mail)
        - SIAE : recherche aussi dans "département", "ville", "code postal", "adresse"
    - affichage du champ CV dans l'admin des utilisateurs
    - ajout de liens direct vers les SIAEs ou organisations de prescripteurs en bas de l'admin des utilisateurs
    - nouveau filtre et lien direct pour trouver et délivrer des PASS IAE en attente de délivrance
- On refuse les SIRET indiqués fermés par la base SIRENE lors de l'inscription des prescripteurs
- Assouplissement des conséquences du déconventionnement d'une structure pendant un délai de grâce de 30 jours

## [1.1.0] - 2020-08-27

### Ajouté
- Import des agréments Pôle emploi d'Août 2020
- Nouvelle page stats basée sur Metabase
- Affichage de l'ID des SIAE dans le tableau de bord (pour faciliter le support)
- Possibilité de distinguer facilement les antennes de structures créées par le support de celles créées par les utilisateurs
- Passage de nos bases de données de staging et de prod en mode "Encrytion at rest"
- Expérimentation : affichage d'une fausse carte dans la page de résultats de recherche

### Modifié
- Nouveau parcours d'inscription des prescripteurs/orienteurs
- Intégrations des modifications de *wording* des e-mails de Nathalie
- Impossible de s'inscrire dans une SIAE qui a déjà des membres (il faut désormais recevoir une invitation)
- Le lien "Répondre aux candidatures reçues" du tableau de bord est transformé en plusieurs liens :
    - "Candidatures à traiter"
    - "Candidatures acceptées et embauches prévues"
    - "Candidatures refusées/annulées"
- Agréments Pôle emploi :
    - amélioration du script d'import pour se baser sur le nom des colonnes plutôt que sur leur ordre dans le fichier source
    - possibilité de filter par date d'import dans l'admin
    - correction d'un bug avec des dates de naissance dans le futur à cause d'un format d'année transmis sur 2 chiffres et transformé en 2068 plutôt que 1968
- Si une fiche de poste est renseignée, le message "Pour optimiser la réception de vos candidatures, pensez à renseigner le descriptif de vos postes et leurs prérequis." n'est plus affiché
- Modification du message d'erreur qui apparait lors de l'inscription Employeur si le SIRET n'est pas reconnu.
- Invitations Prescripteurs : un membre d'une organisation Pôle emploi ne peut inviter que des personnes dont l'adresse e-mail finit en "@pole-emploi.fr".
- Evolution des _fixtures_ pour refléter les derniers changements. 

### Supprimé
- 154 SIAE fantômes pour débloquer les créations légitimes d'antennes
- 7 SIAE sans membres
- 43 organisations de prescripteurs sans membres
- Ancienne application `stats`

## [1.0.9] - 2020-08-13

### Ajouté
- Import des agréments Pôle emploi de Juillet 2020
- Ajout de liens vers YouTube et LinkedIn dans le footer
- Affichage aux DE et prescripteurs de la lettre de motivation envoyée dans leurs candidatures
- Ajout d'une possibilité de connexion automatique aux différents comptes de tests dans l'environnement de Démo
- Import des données DE en provenance de PE connect

### Modifié
- Évolution du tri pour que les SIAEs actuellement en mesure de recruter soient affichées en premier
- Possibilité d'embaucher pour une durée d'une seule journée
- La modale de consentement des cookies devient un bandeau pour une meilleure accessibilité du service
- Suppression du code secret lors de l'inscription des orienteurs
- Affichage des candidatures qu'un orienteur a envoyé avant de créer son organisation
- Possibilité de retrouver facilement dans l'admin des candidatures avec des PASS IAE en attente de délivrance manuelle
- "Recevoir des candidatures" devient "Publier la fiche de poste" dans l'UI d'ajout de fiche de poste
- Mise à jour de Django en version 3.1 et des dépendances Python du projet

## [1.0.8] - 2020-08-03

### Ajouté
- Un prescripteur peut inviter ses collaborateurs à joindre son organisation
- [Simulateur de la demande d'aide
du Fonds Départemental d'Insertion (FDI)](http://fdi.inclusion.beta.gouv.fr/)
- Une embauche reportée permet maintenant un nouveau diagnostic
- Un diagnostic a maintenant une durée de vie limitée
- Nouveau lien "Liste des critères d'éligibilité" sur le tableau de bord Employeur
- Nouveau texte sur le tableau de bord Employeur pour informer du fait que les agréments ont été allongés
- Hotjar sur le Forum

### Modifié
- Déblocage Mailjet permettant à certains utilisateurs de pouvoir recevoir nos emails correctement
- Désactivation de 200 structures n'ayant pas de conventionnement valide à ce jour
- Un prescripteur ayant été détaché de son organisation peut maintenant continuer à utiliser la Plateforme sans erreur

## [1.0.7] - 2020-07-17

### Ajouté
- Déploiement - PACA + Corse (6 juillet)
- Import des agréments Pôle emploi de Juin 2020 (9 juillet)
- Import de nouvelles agences Pôle emploi (14 juillet)
- Allongement des agréments de 3 mois pour les PASS IAE créés avant le 17 juin 2020
- Ajout de `meta property` SEO pour que l'image et la description du service remonte lors d'un partage sur Facebook ou autre
- Ajout de la possibilité de rechercher par ID dans l'admin (agréments, utilisateurs, organisations et structures)
- Ajout de la possibilité de corriger les adresses email utilisateurs dans l'admin
- Ajout d'un contrôle sur la date de naissance du candidat qui doit être âgé au minimum de 16 ans

### Modifié
- Amélioration de la visibilité de la liste de résultats des employeurs solidaires après une recherche
- Clarification des termes ambigus fiche/fiche de poste
- Mise en avant du bouton de filtre des candidatures : "Rechercher dans vos candidatures"
- Clarification du fait que l'email ASP attendu pour les SIAE est l'email du référent technique extranet ASP
- Retrait de l'exemple "Linkedin" pour les propositions de solutions de partage de CV
- Suppression du bouton "Vous êtes une entreprise avec un besoin de recrutement"
- Modification du bandeau inscription SIAE "'Les inscriptions s'ouvrent aux régions progressivement. Vérifiez que la Plateforme est bien disponible sur votre territoire. Seules les ETTI sont ouvertes en France entière."
- Amélioration de la visibilité du bouton multi-structures

## [1.0.6] - 2020-07-02

### Ajouté
- Déploiement - Bourgogne-Franche-Comté (22 Juin)
- Déploiement - Auvergne-Rhône-Alpes (29 Juin)
- Import de nouvelles structures en provenance de l'ASP (25 Juin)
- Messages explicatifs sur l'écran d'inscription des employeurs pour faire comprendre aux employeurs qui sont hors des départements ouverts qu'ils ne peuvent pas encore s'inscrire
- Modale pour donner davantage d'explications quand on a pas d'email
- Nouvel environnement de démo
- Re-calcul des coordonnées géographiques en cas de changement d'adresse dans l'admin SIAE et dans l'admin Organisations de prescripteur
- Un employeur solidaire peut inviter un collaborateur à rejoindre sa structure
- Ajout d'un filtre "date de naissance" dans la recherche d'agréments Pôle emploi
- Blocage des candidatures

### Modifié
- Les critères d'éligibilité simplifiés ETTI deviennent permanents
- "Modifier les coordonnées" devient "Modifier la fiche" sur le tableau de bord des SIAE et des prescripteurs habilités
- Modification de la mention mention RGPD demandée par la DGEFP/PE sur les écrans d'inscription
- "Je donne mon avis" est affiché seulement sur la HP

## [1.0.5] - 2020-06-18

### Ajouté
- Possibilité de finaliser une embauche sans demander de PASS IAE
- Documentation sur l'architecture des prescripteurs
- Gestion du consentement des cookies via Tarteaucitron
- Suivi Hotjar après consentement
- Possibilité de rechercher des prescripteurs "habilités"
- Fiches des prescripteurs "habilités"
- Lien direct vers la fiche d'un prescripteur habilité depuis le tableau de bord

### Modifié
- Réduction du poids de la bannière SVG de la page d'accueil
- Correction du mail envoyé à l'équipe lorsqu'un prescripteur rejoint une organisation sans membres
- Pied de page : remplacement du lien "Nous contacter" par "Besoin d'aide ?"
- Modification du mail envoyé au candidat, lorsqu'une candidature a été effectuée pour lui, afin de l'inciter à se connecter à son compte
- L'émetteur du PASS IAE devient non modifiable dans l'admin des candidatures
- Correction de l'email d'authentification de 50 structures

## [1.0.4] - 2020-06-04

### Ajouté
- Indicateur de validation de l'email dans l'admin (partie utilisateur)
- Envoi d'un email au support lors du rattachement d'un prescripteur à une structure sans membres
- Inscription sans boite email (redirection vers PE connect) 
- Connexion via PE Connect
- Tracking Matomo pour PE Connect
- Liens Typeform lors de l'envoi d'emails (confirmation d'embauche pour les SIAE et prescripteurs)
- Possibilité de pouvoir embaucher sans obtenir de PASS IAE

### Modifié
- Correction d'un problème de vérification de doublon d'email lors de l'inscription d'un prescripteur
- Reformulation des messages d'information et d'erreur lors de la création d'une structure
- Uniformisation des logos ("Plateforme de l'inclusion")
- Email envoyé au candidat lors d'une candidature effectuée pour lui

### Supprimé
- Bouton "Voir la carte"

## [1.0.3] - 2020-05-25

### Ajouté
- Sondage sur l'affichage des résultats re recherche sur une carte
- Mécanisme d'export des PASS IAE au format Excel
- Message d'information au candidat à propos de l'utilisation de ses données personnelles au moment de la création de son compte
- Ajout du logo Pôle emploi dans la page de création de compte prescripteur
- Derniers réglages du process de vérification de l'habilitation des organisations de prescripteurs
- Possibilité de rechercher par code Safir dans l'admin des organisations de prescripteurs
- Import de 11 nouvelles structures en provenance de l'ASP

### Modifié
- Ré-ouverture des embauches pour toutes les structures
- Factorisation de la vérification de permissions des SIAE et des prescripteurs
- Allongement du nombre de caractères permis dans le champ CV (500 max)
- Allongement de la durée de rétractation d'un employeur sur une candidature jusqu'à 96h (cas des weekends)
- Mise à jour du Docker de développement vers PostgreSQL 12
- Lorsqu'un utilisateur modifie sa date de naissance, il n'y a plus de date par défaut
- Les champs "date" suivent désormais le format JJ/MM/AAAA et ont un "placeholder" JJ/MM/AAAA/
- Résolution de bugs mineurs sur la page statistiques (sécurité du formulaire, encoding de caractères spéciaux, problème de cache)

## [1.0.2] - 2020-05-12

### Ajouté
- Déploiement - Hauts-de-France (27 Avril)
- Nouveau design en accordéons et nouveaux tableaux par région sur la page stats
- Bornes minimum et maximum des années dans le datepicker
- Contrôle sur la date de naissance (pas avant 1900)
- Lorsqu'un prescripteur envoie une candidature, toute la chaîne est notifiée (SIAE, prescripteur, candidat)
- Affichage du caractère habilité d'un prescripteur sur le tableau de bord le cas échéant
- Possibilité pour un candidat de rajouter un lien vers un CV dans son profil
- Ajout du champ "CV" à une candidature

### Modifié
- L'adresse candidat devient obligatoire à la validation de l'embauche si la structure de l'employeur est soumise aux règles de l'éligibilité
- Correction d'un bug du champ ville non mémorisé dans la recherche
- Affichage du bouton "Vous êtes une entreprise (hors IAE) avec un besoin de recrutement" uniquement aux utilisateurs non connectés
- Le bouton "Télécharger l'attestation" ne s'affiche pas si l'annulation d'une candidature est possible

### Supprimé
- Message concernant la crise sanitaire

## [1.0.1] - 2020-04-27

### Ajouté
- Possibilité d'annuler un agrément
- Déploiement - Ile-de-France (14 Avril)
- Déploiement - Grand Est (20 Avril)
- Renforcement de la politique de mots de passe conformément aux recommandations de la CNIL (au moins 3 des 4 types suivants : majuscules, minuscules, chiffres, caractères spéciaux)
- Nouveau mode d'inscription des prescripteurs (contrôle de l'email et du code Safir pour Pôle emploi, demande de vérification d'habilitation manuelle pour les structures non existantes)
- Système de blocage du compte pendant 5 minutes au bout de 5 tentatives d'authentifications échouées
- Injection de 151 nouvelles SIAE obtenues en combinant deux nouveaux exports ASP de février et avril 2020

### Modifié
- Correction d'une erreur 500 lors de la création de `Siae` ou `PrescriberOrganization` dans l'admin dans les cas où on ne renseigne pas l'adresse
- Empêchement de l'énumération d'utilisateurs par le formulaire de réinitialisation de mots de passe
- Rétablissement du message de succès "simple" après l'acceptation d'une candidature (celui d'avant l'Opération ETTI)
- Correction d'un bug de code postal lors de l'ajout d'une structure en Corse
- Correction d'un bug de lien non cliquable à cause du widget "Je donne mon avis"

### Supprimé

## [1.0.0] - 2020-04-13

### Ajouté
- Création de ce changelog
- Liste des collaborateurs d'un employeur solidaire
- Liste des collaborateurs d'un orienteur/prescripteur
- Bouton "Vous êtes une entreprise avec un besoin de recrutement"
- Vérification des adresses email lors de la création de comptes avant de pouvoir se connecter
- Possibilité de renseigner l'adresse postale du candidat pendant inscription/profil/candidature
- Nouveau type d'employeur solidaire "EATT" (Entreprise adaptée de travail temporaire)
- Message "mobilisationemploi.gouv.fr" sur le tableau de bord

### Modifié
- Critères administratifs simplifiés pour les ETTI pour la période Covid-19 du 08/04 au 30/04 (1 critère niveau 1 ou 2 critères de niveau 2)
- Mise à jour des agréments Pôle emploi
- Remplacement du terme "Agrément" par "PASS IAE"
- Améliorations des recettes jetables (tendre vers l'ISO prod, accélération de la création avec un dump SQL etc.)
- Fix lien de téléchargement de l'attestation Covid-19
- Fix lien vers la FAQ dans le pied de page
- Restriction d'embauche temporaire pour les ETTI hors 62-67-93 (jusqu'au 10/04/2020)
- Les fiches des employeurs solidaires sont publiques ("Opération ETTI")
- Fix page stats erreur 403 à cause du token CSRF

### Supprimé
