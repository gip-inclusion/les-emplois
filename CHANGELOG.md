# Journal des modifications

## [18] - 2021-05-06

### Ajouté

- Ajout d'un [journal des modifications](https://emplois.inclusion.beta.gouv.fr/versions/)
- Ajout d'un export CSV des candidatures pour les employeurs et prescripteurs
- Ajout d'un contrôle qui assure que la date de fin de contrat n'est pas postérieure à la date de fin du PASS IAE
- Mise en avant du forum sur le tableau de bord
- Ajout d'un contrôle de la date de début d'une prolongation dans l'admin
- Ajout de la possibilité de créer des PASS IAE ex nihilo dans l'admin
- Sondage pour améliorer l'UX du moteur de recherche
- Ajout d'une mention "Le prescripteur a dérogé au délai de carence, vous pouvez obtenir un PASS IAE." pour les PASS IAE expirés
- Ajout de composants techniques en préparation de l'envoi des fiches salarié à l'ASP
- Activation des transactions au niveau de chaque appel à la base de données

### Modifié

- Nouvelle numérotation des PASS IAE : les 2 chiffres après 99999 ne correspondent plus à l'année et continuent de s'incrémenter
- Modification d'une mention confusante pour les employeurs ne demandant pas de PASS IAE
- Correction d'un titre incorrect lorsqu'un prescripteur postule pour un candidat
- Les boutons "besoin d'aide" renvoient maintenant vers le portail assistance
- Un nouveau prescripteur peut maintenant créer son compte même quand les coordonnées GPS de API entreprise ne sont pas valides
- Mise à jour technique vers Django 3.2.2

### Supprimé

- Le numéro de PASS IAE n'est plus visible sur les candidatures en attente

## [17] - 2021-04-23

### Ajouté

- Ajout de l’interface "Mes annexes financières"
- Ajout d’un formulaire pour connaitre le secteur d’activité des employeurs
- Ajout d’une redirection de `inclusion.beta.gouv.fr/dashboard` vers `emplois.inclusion.beta.gouv.fr/dashboard` pour ne pas induire en erreur les usagers suite au changement de nom de domaine.
- Ajout de la colonne "date de création" pour permettre au support de voir les structures créés lors des imports.

### Modifié

- Nouvelle version majeure de Django v3.2
- Changement du code de tracking Hotjar
- Amélioration des performances de l'enregistrement de la session utilisateur
- Correction du bug qui empeche la prolongation d’une ACI pour "difficultés particulières"
- Possibilité de modifier l’email d’un demandeur tant que celui ci n’a pas confirmé son compte
- Simplification des invitations:
  - Les invitations ne partent plus en plusieurs exemplaires quand l'utilisateur clique à répétition sur le bouton d'envoi
  - Si une invitation est renouvelée pour un utilisateur, il n'y a plus de nouvelle invitation créée en base (moins d'entrées dans le tableau de bord)
  - Environ 4500 invitations en doublon ont été supprimées de la base de données
- Correction de l’affichage des emails où des éléments sur les structures manquaient.
- Amélioration de l’affichage des critères d’éligibilité pour les candidatures envoyées par des prescripteurs habilités
- Utilisation d’une compte dédié pour les emails de la plateforme, afin de réduire le risque de classification en spam des emails applicatifs.

### Supprimé

- Suppression du mécanisme de traduction. Ce système était une contrainte pour le développement et les chaines n'ont jamais été traduites dans une autre langue (et quid des annonces, des commentaires utilisateur, etc.)

## [16] - 2021-04-08

### Ajouté

- Ajout du nouveau type ACIPHC, Atelier chantier d'insertion premières heures en chantier
- Le super utilisateur peut maintenant modifier l'état d'une habilitation depuis l'interface d'administration
- Ajout d'un outil d'analyse de couverture de code par les tests
- Sérialisation JSON des fiches salarié avec l'ASP
- Nouvelle documentation du projet générée à partir du Markdown et incluant Whimsical sur :
  - les outils de développement
  - quelques fonctionnalités importantes du projet
  - le détail des différentes commandes d'import (SIAE, AE, Metabase, etc)

### Modifié

- Mise à jour vers Django 3.1.8 pour prendre en compte un correctif de sécurité
- Amélioration des scripts d'import des données dans Metabase
- Correction d'un bogue quand la date de début d'un PASS est recalculée
- Remplacement des dernières occurrences de « plateforme »
- Amélioration de l'import fluxIAE et ajout de nouveaux flux
- Ajout d'un timeout aux appels à PDF Shift pour éviter que les requêtes restent en suspens quand le service ne réponds pas
- Réduction du nombre de requêtes SQL à l'import des comptes Pôle Emploi
- Correction des données de test en recette jetable
- Amélioration de l'accès aux données de la session utilisateur pour éviter l'utilisation de données incomplètes
- Remplacement de l'email d'assistance par le portail assistance
- Remplacement de la génération du nom utilisateur fournie par une librairie externe qui générait de nombreuses erreurs.
- Affichage plus amical des erreurs de transaction, ces erreurs peuvent se produire lorsque un utilisateur effectue une action déjà effectuée (page non actualisée)
- Correction des données de tests
- Le script de téléchargement de la base de données de production récupère seulement la sauvegarde la plus récente
- Changement du logo du Ministère en entête

### Supprimé

- La documentation technique n'est plus dans gitbook

## [15] - 2021-03-25

### Ajouté

- Mise en avant des candidatures sans activité depuis plus de 3 semaines pour les employeurs et prescripteurs
- Affichage d'un message si une fiche de poste a déjà reçu beaucoup de candidatures dans les résultats de recherche ("Plus de 20 candidatures reçues")
- Mise en avant du contrat de professionnalisation lors de la demande d'un PASS IAE
- Affichage et modification des informations d'un candidat par les prescripteurs pour pouvoir les modifier après envoi d'une candidature
- Ajout des modèles de base de données des fiches salarié et du profil de demandeur d'emploi
- Possibilité pour un conseil départemental de visualiser ses organisations conventionnées avec les membres
- Ajout du champ "Date de création" dans l'export des PASS IAE
- Ajout d'un message d'avertissement aux prescripteurs : "Les coordonnées de contact de votre organisation sont visibles par tous les utilisateurs connectés"
- Affichage des dates de début et de fin du PASS IAE dans l'e-mail de confirmation d'envoi du PASS ("Valide du … au …")
- Possibilité de modifier les informations d'un candidat quand sa candidature es à l'état "Nouvelle candidature" (auparavant possible uniquement sur "Candidature à l'étude" et "Candidature acceptée")
- Affichage du badge "Priorité aux bénéficiaires de RQTH" pour les EATT dans les résultats de recherche
- Ajout d'une mention "Accessibilité : non conforme" dans le pied de page
- Ajout d'outils de vérification de la qualité du code

### Modifié

- Mise à jour majeure du langage Python de la version 3.7 à la 3.9 et des dépendances Python du projet
- Correction d'un bogue relatif à la prise en compte de la prolongation COVID pour les agréments en provenance de Pôle emploi
- Les informations du PASS IAE sont visible quand il est expiré : si une candidature est envoyée par un prescripteur habilité pour un candidat en période de carence et qu'elle est toujours en attente de traitement, alors on masque le caractère "expiré" ainsi que les dates du PASS IAE pour ne pas qu'un employeur refuse la candidature en pensant que le PASS est expiré. Dans tous les autres cas, on affiche la mention "expiré" avec les dates du PASS IAE.
- Amélioration des termes relatifs à la distance sur la recherche : on remplace "à 5km de Metz" par "à 5km du centre de Metz"
- Sur le tableau de bord des employeurs, le texte du lien "Configurer vos fiches de postes" devient "Publier/gérer les fiches de postes"
- Désactivation de l'auto-complétion du champ "E-mail personnel du candidat" dans le tunnel de candidature (pour éviter de se tromper pendant la saisie d'un email de candidat)
- On affiche plus le lien complet du CV pour éviter de casser la mise en page quand le lien est trop long, à la place on a un lien intitulé "Lien vers le CV"
- Admin des prescripteurs et des employeurs :
  - possibilité de supprimer les coordonnées géographiques
  - possibilité de demander un re-calcul des coordonnées géographiques
  - possibilité de modifier une adresse sans toucher aux coordonnées géographiques
  - possibilité de modifier les coordonnées géographiques sur une carte
- Correctif pour que notre mécanisme d'intégration continue puisse vérifier la présence de migrations de base de données manquantes

### Supprimé

- Suppression du message d'alerte "Notre nom de domaine change pour emplois.inclusion.beta.gouv.fr"

## [14] - 2021-03-11

### Ajouté

- Ajout de la possibilité de se désabonner de certaines notifications :
  - nouvelle candidature spontanée
  - nouvelle candidature pour une fiche de poste
- Ajout des dates de contrat dans le mail de notification d'embauche
- Gestion de la prolongation des PASS IAE

### Modifié

- Améliorations de l'interface de configuration des fiches de poste
- Mise à jour du logo pour rester cohérent suite au changement du nom de domaine `inclusion.beta.gouv.fr` vers `emplois.inclusion.beta.gouv.fr`
- Remplacement du texte *Plateforme de l'Inclusision* par *Les emplois de l'inclusion*
- Changement des coordonnées GPS de Berre-l'Étang
- L'attestation du PASS IAE est maintenant téléchargeable même lorsque le PASS IAE est expiré
- Possibilité pour un employeur d'accepter une candidature dont le statut est "Embauché ailleurs"

### Supprimé

- Suppression du délai d'1h avant de pouvoir repositionner un candidat en tant que SIAE
- Suppression de certaines notifications employeur et prescripteur :
  - nouveau membre
  - invitation acceptée

## [13] - 2021-02-25

### Ajouté

- Un nouveau compte de démonstration est disponible pour les E.A. (Entreprise Adaptée) avec connexion automatique
- Résultats de recherche employeurs : ajout d'une étiquette "Priorité aux bénéficiaires de RQTH" aux entreprises adaptées
- Metabase : ajout de trois colonnes à la table Organisations (date_dernière_candidature, latitude et longitude) et transformation de la colonne temps_écoulé_depuis_dernière_candidature en date_dernière_candidature
- Metabase : ajout de deux colonnes à la table Candidatures (nom_org_prescripteur et safir_org_prescripteur)
- Création d'un sous-domaine assistance.inclusion.beta.gouv.fr pour le support
- Les employeurs peuvent modifier la date de début de leurs embauches qui n'ont pas encore démarré. Cela entraîne la modification du début du PASS IAE le cas échéant
- Point d'accès API permettant aux éditeurs de logiciel de récupérer des fiches salarié de test. [Ce point d'accès a une documentation](https://github.com/betagouv/itou/blob/master/itou/api/README-FS-SSII.md)
- Fiches salarié: ajout d'un profil utilisateur pour compléter les données personnnelles du salarié

### Modifié

- Autocomplétion de la recherche par ville : affichage des 12 derniers résultats (au lieu de 10)
- Formulaire d'acceptation d'une candidature : "Date de fin de contrat" remplacé par "Date prévisionnelle de fin de contrat"
- Résolution d'un bug qui rompait la communication entre Typeform et notre service, entrainant une mauvaise sauvegarde des CV depuis le 22 janvier. Les CV en question ont pu être reliés à leurs candidats a posteriori
- Montée en version de Django (3.1.7)
- Modification de la méthode qui renvoie les agréments disponibles pour un candidat (Pôle emploi / PASS IAE) pour favoriser les PASS IAE valides le cas échéant
- Fiches salarié: simplification des référentiels de données ASP

### Supprimé

- Résultats de recherche employeurs : suppression de la distance entre une structure et la ville recherchée

## [12] - 2021-02-12

### Ajouté

- A la saisie du message de candidature par une SIAE, il est précisé que ce message sera visible par le prescripteur et le demandeur d'emploi
- Affichage pour le prescripteur et le demandeur d'emploi de la raison de la mise en file d'attente d'une candidature
- Ajout d'un bouton non-contextuel vers la FAQ en bas de page (absent sur mobile et page d'accueil)
- La liste des suspensions de PASS IAE est disponible dans l'export Excel
- Mise en place d'alertes en cas de problème du système d'envoi d'e-mails (suite à incident)

### Modifié

- Améliorations mineures des scripts d'import GEIQ/SIAE/EA
- Mise à jour vers Django 3.1.6
- Amélioration du traçage des erreurs lors d'un problème d'import de données PE Connect
- Django Admin : correction de l'export Excel des PASS IAE
- Django Admin : correction d'un problème de performance dans la gestion des données externes PE Connect
- Django Admin : correction de la gestion des notifications des employeurs

## [11] - 2021-01-28

### Ajouté

- Import et traitement des fichiers de référence ASP pour les fiches salarié
- Les employeurs peuvent modifier les informations des candidatures :
  - pour les candidats considérés comme "autonomes"
  - si la candidature est en attente ou acceptée
- Affichage de l'identifiant Pôle emploi :
  - dans le détail d'une candidature
  - dans le PDF du PASS IAE
- Nouveau logo "Ministère du travail, de l'emploi et de l'insertion" dans le pied de page

### Modifié

- Changement des noms de domaine :
  - `inclusion.beta.gouv.fr` **devient** `emplois.inclusion.beta.gouv.fr`
  - `staging.inclusion.beta.gouv.fr` **devient** `staging.emplois.inclusion.beta.gouv.fr`
  - `demo.inclusion.beta.gouv.fr` **devient** `demo.emplois.inclusion.beta.gouv.fr`
- Correctif d'un problème de performance de l'export des PASS IAE via l'admin
- Dans "Gérer des collaborateurs" on affiche uniquement les invitations **non expirées**
- Simplification des étapes de diagnostic :
  - le critère "Primo arrivant" devient "Primo arrivant (personne récemment arrivée en France avec un contrat d'intégration républicaine de moins de 24 mois)"
  - simplification du texte du préambule et ajout d'explications différentes pour les prescripteurs habilités et les SIAE
- Correctif pour la requête qui affiche la liste des candidatures des prescripteurs, on n'affiche plus que :
  - celles éventuellement émises par l'utilisateur connecté en tant qu'orienteur (avant d'avoir rejoint une organisation)
  - celles de l'organisation active

### Supprimé

- Suppression de la mention "Agrément expiré" dans les candidatures envoyées aux SIAE par des prescripteurs habilités pour des candidats en période de carence
- Suppression des mentions "pièces justificatives" dans l'écran de validation des critères d'éligibilité des prescripteurs
- Simplification des étapes de diagnostic :
  - suppression de la partie "Diagnostic socio-professionnel de référence" (le gros tableau)
  - suppression du bloc jaune "Vous postulez pour X" dans le tunnel de candidature, le nom complet est déplacé dans le titre "Postuler pour X chez Y" à la place
  - suppression des mentions "Critères administratifs" dans le diagnostic pour les prescripteurs habilités

## [10] - 2021-01-14

### Ajouté

- Ajout d'un filtre sur les candidatures : "PASS IAE suspendu"
- Les suspensions de PASS IAE peuvent être modifiées et supprimées
- Page d'accueil : affichage des prochains webinaires
- Page de gestion de candidature : ajout d'un message informatif
- Django Admin : ajout du lien permettant d'accepter une invitation
- Django Admin : affichage de certains identifiants
- Django Admin : rubrique "log des transitions des candidatures", recherche par identifiant de candidature
- Ajout d'informations dans l'email de candidature à destination des employeurs
- Affichage de la date à laquelle il sera possible de télécharger un PASS IAE
- Tableau de bord employeur : mise en avant des auto-prescriptions à travers l'ajout d'un badge

### Modifié

- Mise à jour vers Django 3.1.5
- Le bouton "Télécharger l'attestation" devient "Télécharger le Pass IAE"
- Le statut de candidature "Embauche pour plus tard" a été remplacé par "Candidature en liste d'attente"

### Supprimé

- Pour les GEIQ et les EA, retrait de la note informative "Pass IAE et demande rétroactive"

## [9] - 2020-12-30

### Ajouté

- Gestion de la suspension de PASS IAE
- Le moteur de recherche des prescripteurs est maintenant public
- 700 EA et EATT ont été ajoutées à la Plateforme
- Import des agréments PE de décembre
- Ajout d'un texte informatif précisant que la date de fin de contrat est indicative et qu'elle n'a aucune conséquence sur les déclarations faites dans l'extranet IAE 2.0 de l'ASP
- Les prescripteurs peuvent maintenant personnaliser le nom de leur organisation comme les employeurs
- Les utilisateurs peuvent maintenant modifier leur email personnel

### Modifié

- La recherche est maintenant sur 5km par défaut au lieu de 25km
- Modification du texte du mail envoyé lors d'un refus d'habilitation

## [8] - 2020-12-03

### Ajouté

- Les prescripteurs peuvent filtrer les candidatures envoyées par structure de destination
- Affichage de l'e-mail de la personne connectée dans le menu déroulant
- Affichage du SIRET dans le tableau de bord des employeurs

### Modifié

- Amélioration du lien "Besoin d'aide ?" qui pointe maintenant directement vers le champ recherche de la FAQ
- Réparation des tests de la plateforme d'intégration continue
- Pérennisation de nouvelles données dans l'espace DEMO
- Anonymisation des téléphones des siaes et organisations dans les fixtures
- Import des agréments PE du mois d'octobre
- Résolution d'un problème d'envoi d'e-mails inopportuns à des utilisateurs désactivés

### Supprimé

- Retrait de la carte montrant la géolocalisation des structures dans l'interface d'administration

## [7] - 2020-11-19

### Ajouté

- Ouverture région Normandie
- Ajout d'un lien vers le décret concernant les critères d’éligibilité
- Ajout d'un message d'information dans la liste des candidatures en attente et dans l'e-mail de nouvelle candidature
- Ouverture région Pays de la Loire
- Inscription possible de plusieurs structures ayant un même SIRET mais des types différents
- Un administrateur de structure peut gérer ses collaborateurs
- Possibilité d'avoir plusieurs administrateurs par structure
- Ajout du lien de la place de marché dans le tableau de bord de certaines SIAE
- Correction d'une erreur d'affichage sur Microsoft Edge et Internet Explorer
- Ajout du type de structure sur le tableau de bord et dans la liste de sélection multi-structure
- Lors d'une candidature, il est désormais impossible d'ajouter un CV hébergé par l'intranet de Pôle emploi
- Les prescripteurs peuvent voir le message de refus des candidatures suivies

### Modifié

- Modification de la couleur du bouton de validation lors d'une demande de PASS IAE
- Modification des informations d'inscription d'un employeur solidaire
- Simplification du code d'ouverture d'une région
- Modification du champ "enseigne" dans la fiche SIAE
- La géolocalisation ne tient plus compte du complément d'adresse (baisse de qualité du score)
- Correction du fonctionnement des recettes jetables
- Modification du mot de passe du super administrateur dans la démo

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
