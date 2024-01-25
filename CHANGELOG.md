# Journal des modifications

## [78] - 2024-01-07

### Ajouté
- Informations pour la création de CV avec le service partenaire _Diagoriente_
- Stats : Publier le TB327 (Suivi du cofinancement des ACI) aux DDETS et CD du 31 et du 84
- En tant que prescripteur qui reçoit un refus pour motif autre je suis invité à contacter l’employeur si je souhaite en savoir +
- Ajout d'une vue d'erreur personnalisée
- Ajout du guide a la prescription dans la navigation pour les employeurs et les prescripteurs habilités
- Métriques : ajout de nouveaux tags matomo sur le tableau de bord employeur

### Modifié
- Correction du filtre "Éligibilité à valider"
- API GEIQ : Utiliser les codes _LABEL_ au lieu des codes _ITOU_
- Admin : Fonction “transfert” des objets puis arriver sur la bonne page
- Déplacement des champs `pole_emploid_id` / `lack_of_pole_emploi_id_reason` vers le modèle `JobSeekerProfile`
- Améliorations UI/UX
- Candidatures : modification du widget des départements & fiches de poste
- Connexion : suppression du lien "Mot de passe oublié" en double

### Supprimé
- Fiches salarié : Suppression de la notion de "FS Orpheline"

## [76] - 2023-12-03

### Ajouté
- PASS IAE AI : message pour les pass arrivant à expiration dans moins de 30 jours #3377 et #3384
- PASS IAE AI : Ajout d’information dans le PASS IAE pour une Prolongation en cours #3323
- PASS IAE AI Admin : filtrer les demandes refusées par date pour les AI #3381 et #3390
- PASS IAE : renvoi à pole emploi lors des changements de dates #3383

### Modifié
- PASS IAE : annuler une suspension #3327

### Supprimé
- Dashboard : retrait du sondage maze #3370

## [75] - 2023-11-19

### Ajouté
- Notification des PASS IAE supprimés à Pôle emploi
- Fiches salarié : Parcours de création autonome
- Fiches Salarié : Prévenir les SIAE du délai d’intégration dans l’Extranet IAE de l’ASP
- API des entreprises à destinations du marché de l'inclusion

### Modifié
- Fiche de poste : correction de l'affichage de la ville d'une fiche de poste en l'absence de l'information
- Candidatures : Permettre de mettre en liste d'attente des candidatures à l'étude nécessitant un diagnostic d'éligibilité
- Libellés : Changement pour les contrats "Convergence" et "Premières Heures"
- Candidatures : Refonte de la carte candidature pour les candidats
- Harmonisation de la zone de boutons dans les formulaires
- Changer certaines bannières infos/alertes par des toasts

## [74] - 2023-11-06

### Ajouté
- Admin : Lister les PASS IAE d'une SIAE sur la page d'admin
- Admin : Permettre à un employeur de desactiver son compte pour devenir prescripteur (ou l'inverse)
- Embauche : l'employeur précise le poste à l'embauche
- Profil salarié : Ajout des dates de PASS IAE sur les cartes

### Modifié
- Carte candidature : harmonisation de la carte en vue prescripteur (avec celle des employeurs)
- Fiches de poste : permettre la suppression de la localisation (pour réutiliser celle du siège, par défaut)
- Fiches de poste : permettre de choisir un poste (code ROME) déjà existant pour créer un poste avec une autre localisation (par exemple).
- PASS IAE : modification de la logique d'envoi à PE : envoi des PASS démarrés, par une tâche planifiée toutes les 5 minutes.
- Annexes financières : Amélioration UI de la liste

## [73] - 2023-10-23

### Ajouté
- Admin : Ajout du lien vers le profil de demandeur d'emploi sur la page d'utilisateur
- Admin : Ajout de la recherche par NIR pour les PASS IAE et prolongations
- Candidatures : Ajout d'actions pour les nouvelles candidatures
- Demandes de prolongations : Affichage du nom du prescripteur habilité sollicité dans la liste de demandes
- Stats : Ajout de stats sur les demandes de prolongations pour les DDETS IAE et DREETS IAE

### Modifié
- Admin : Ne pas définir de mot de passe pour les nouveaux utilisateurs créés via l'admin
- API: Correction de l'inversion nom/prénom de l'API candidats
- Candidatures : Repositionner les boutons actions en haut à droite
- Contrôle a posteriori : Correction du mail de rappel des institutions
- Contrôle a posteriori : Amélioration du statut en phase 3
- Demandes de prolongations : Correction de la redirection pour les utilisateurs non-connectés
- Demandes de prolongations : Ne plus proposer les organisations auxquelles les prescripteurs n'appartiennent plus
- Espace connecté : Changement de l'url de base du site
- Import ASP : Correction de l'inférence du format de date
- Pôle Emploi Connect : Refonte technique du connecteur
- Performances : Améliorations du temps d'affichages de certaines pages
- Tableau de bord : Correction du nom de l'admin à contacter en cas d'adresse mal géolocalisée
- Tableau de bord : Correction du fil d'ariane
- Tableau de bord : Suppression d'un badge nouveau

## [72] - 2023-09-25

### Ajouté
- Connexion : séparation de la connexion et de l’inscription
- Demandes de prolongation : procédure de refus (motifs et actions proposées)

### Modifié
- Fiches salarié : amélioration de la page "fiches salarié à mettre à jour"
- Fiches de poste : amélioration de l'interface de gestion
- PASS IAE : retrait de l’acceptation automatique à J+30 et modification des relances par e-mail

## [71] - 2023-09-11

### Ajouté
- Candidatures : Ajout de la civilité dans les exports de candidatures
- Contrôle a posteriori : Mettre à dispo le lien du calendrier de la campagne de contrôle côté SIAE
- Déclaration d'embauche : Nouveau processus de déclaration d'embauche rapide
- Demandes de prolongations : Ajout de filtres pour faciliter la navigation
- UX : Ajout de la bannière livestorm au tableau de bord des prescripteurs et employeurs

### Modifié
- Admin : Ajout d'un champ commentaire sur la page d’une campagne de contrôle a posteriori
- Admin : Permettre aux membres du support de transférer les objets d’un candidat vers un autre
- Admin : Restriction de certaines opération dangereuses
- Candidatures : Ne plus afficher le PASS IAE dans le parcours d'embauche pour les structures non concernées par l'IAE
- Correction des exports vers Metabase
- Prolongations : Renouvellement des prolongations par périodes d’un an
- Prolongations : Amélioration du contenu de l'email de demande de prolongation
- Stats : Utilisation de la nouvelle page de statistiques
- Thème : MaJ du thème itou vers la version 0.7.5
- UX : Correction du format des dates dans les messages d'erreur
- UX : Harmoniser l'affichage du nom des utilisateurs


## [70] - 2023-08-28

### Ajouté
- GEIQ : API embauches à destination de la FFGEIQ et des logiciels de gestion des GEIQ
- Contrôle a posteriori : retrait du rappel lorsque les SIAE restantes n'ont pas soumis de documents
- Contrôle a posteriori : le contrôle d’une candidature n'est pas affiché tant que son état n’est pas officiel
- Candidatures : affichage de l'éligibilité IAE dans la liste des candidatures SIAE
- Candidatures : les candidatures sont bloquées pour les SIAE sans membre actif

### Modifié
- MaJ du thème itou vers la version 0.7.4
- Candidatures : améliorations dans l'affichage des étapes (gabarits)


## [69] - 2023-08-16

### Ajouté
- Admin : retour sur l'admin quand on relâche un utilisateur détourné

### Modifié
- Modification du menu "besoin d'aide"
- Parcours de candidature : modifications et corrections
- CSP : Améliorations et corrections des règles CSP
- PASS IAE : modification de la période durant laquelle les prolongations sont possibles


## [68] - 2023-07-31

### Ajouté
- PASS IAE : ajout des demandes de prolongation
- GEIQ : déclaration une embauche faite dans le cadre de l'expérimentation VAE inversée
- Fiches salarié : les créations tardives ne sont plus archivées instantanément
- Contrôle a posteriori : configuration du début de la phase contradictoire
- Contrôle a posteriori : recherche des SIAE évaluées par SIRET
- Contrôle a posteriori : notification des DDETS lors du passage en phase 2 & 3 bis

### Modifié
- Imports ASP : certaines SIAE émettrices d'un diagnostic lié à un PASS IAE ne sont plus supprimées automatiquement
- Admin : amélioration des performances, rubrique "Utilisateurs"
- Modifications diverses suite au passage à Zendesk


## [67] - 2023-07-17

### Ajouté
- Liste des PASS IAE : amélioration des performances
- Parcours d'embauche : vérification des permissions des utilisateurs
- Bilans de prolongation : disponibles que pour les AI


### Modifié
- Admin : ajout du bouton "détourner" sur la vue de détails d'un utilisateur
- Prolongations : toutes les SIAE peuvent effectuer une prolongation (si la candidature est diponible dans leur carnet de bord)


## [66] - 2023-07-03

### Ajouté
- Contrôle a posteriori : affichage du calendrier de la campagne en cours
- Employeurs : proposer la clôture d'un PASS IAE suite à 12 mois consécutifs de suspension
- Fiches de poste : suivre leur statut d'activation dans le temps
- Fichier des rejets Pole Emploi : ajout de la raison sociale et du type de SIAE
- Profils demandeur d'emploi : afficher le statut de certification Pôle Emploi dans l'admin

### Modifié
- Améliorations d'interfaces, de formulations et de rendus divers
- Candidatures : cacher les adresses e-mail aux candidats
- Candidatures : proposer des pages de retour plus intuitives
- Critères administratifs : ne peuvent être ajoutés ou modifiés dans l'admin



## [65] - 2023-06-19

### Ajouté
- Contrôle a posteriori : validation automatique des revues complètes de la DDETS au passage en phase contradictoire et à la clôture de la campagne
- Fiches de poste : ajout de valeurs par défaut sur certains champs pour faciliter la lisibilité
- Inclusion Connect : permettre le parcours d'inscription à travers plusieurs navigateurs

### Modifié
- Candidatures : le champ "nombre de jours de formation" devient "nombre d'heures de formation"
- Contrôle a posteriori : différer la transmission du mail de résultat
- Contrôle a posteriori : modification du tableau de bord pour les SIAEs
- Contrôle a posteriori : modifications de wording dans les emails et statuts dans certaines phases
- Employeurs : correction d'une régression qui empêchait la sélection de SIAES du même SIRET
- Inclusion Connect : disponible uniquement pour prescripteurs et employeurs
- Inclusion Connect : rendre la déconnexion compatible OIDC
- Le fichier bilan pour les prescripteurs habilités est téléchargeable au format XLSX
- Parcours d'embauche :	ne pas afficher les GEIQ, EA, EATT et OPCS comme des SIAE.



## [64] - 2023-06-05

### Ajouté

- N'autoriser que des prescripteurs à rejoindre des organisations
- Création automatique d'un profil à la création d'un demandeur d'emploi
- Gestion des salariés et PASS IAE : modification des infos personnelles d'un candidat même sans candidature
- GEIQ: ajout de champs à la candidature relatifs à la qualification et la formation

### Modifié

- Modifications diverses de l'affichage du détail de candidature
- Suppression des mentions de l'API Entreprise de `api.gouv.fr`
- MaJ du thème itou vers la v0.6.8, de l'entête et de tarte au citron
- MaJ de l'UI des "cards" du dashboard


## [63] - 2023-05-22

### Ajouté

- « Extranet EA 2 » est ajouté dans une bannière d’info présente lors de l’inscription des employeurs.
- GEIQ - Embauche : Ajout du nombre de jours d’accompagnement avant contrat.
- Candidature : ajout des informations de NIR dans les parcours de création ou mise à jour des profils de demandeur d'emploi.
- Django admin : permettre d'ajouter un profil candidat à partir d'une fiche salarié.
- Ajout d'un texte explicatif avant le formulaire d'inscription des facilitateurs.

### Modifié

- Les prescripteurs habilités peuvent accéder au diagnostic à partir de la page dédiée à la situation administrative du candidat.
- Controle a posteriori: ouverture de la phase 1
- import_geiq/ea_eatt: les SIAE créées par des utilisateurs ne sont plus supprimées automatiquement.
- Boost UX / UI : diverses modifications de formulations et de positionnements.
- Diverses améliorations d'accessibilité.
- Carte PASS IAE : mise à jour de l'affichage de la date de fin prévisionnelle des PASS IAE.
- inclusion_connect: autoriser les prescripteurs de se connecter depuis la page des employeurs (et reciproquement).
- Exclusion des membres inactifs des exports CTA.



## [62] - 2023-05-08

### Ajouté

- Alimentation automatique des listes de diffusion avec les nouveaux prescripteurs et employeurs

### Modifié

- Inclusion Connect : son utilisation est maintenant obligatoire pour tous les prescripteurs et employeurs
- Pass IAE : affichage du nombre de jours restants au lieu de la date de fin
- Candidatures : amélioration de la géolocalisation des adresses candidats et employeurs
- Améliorations diverses de HTML (meilleure accessibilité et correction de défauts de rendu)
- UI : harmonisation des badges
- UI : amélioration de la page pour inviter des collaborateurs
- UI : amélioration du tableau de bord prescripteur
- Suppression du message d'aide « Par exemple 0610203040 »
- Suppression du pre-header
- Pied de page : affichage de cette année (et non de 2021...)
- Remplacer « Proposer votre|une candidature » par « Postuler »
- Tableau de bord des candidats : affichage conditionnel du titre de la colonne « PASS IAE » et élargissement de la colonne.


## [61] - 2023-04-24

### Ajouté

- GEIQ : Ouverture du parcours auto-prescription

### Modifié

- API : Correction de multiples erreurs dans la documentation du schéma
- Améliorations diverses de HTML (meilleure accessibilité et correction de défauts de rendu)
- Candidatures : Affichage des critères administratifs du diagnostic d’éligibilité sur les cartes
- Candidatures : Amélioration UI de la liste de candidatures
- Candidatures : Indication de la durée en semaines pour laquelle une candidature est restée sans réponse
- Contrôle a posteriori : Retrait de l’option pour se désinscrire d’une campagne
- GEIQ : Clarification du texte d’éligibilité jeunes -26 ans
- Gestion d’organisation : Passage en lecture seule pour pôle emploi
- Métiers et recrutement : Amélioration de l’affichage de la liste

## [60] - 2023-04-11

### Ajouté

- API : Possibilité de créer son token d’accès
- Fiches salarié : Ajout du filtre par nom du candidat à la liste des fiches salarié
- GEIQ : Ajout d'actions préalables à l'embauche

### Modifié

- Fiches salarié : Précision du message d’erreur lors de la création quand lorsqu’une fiche archivée existe
- Liste des candidatures : Légère correction en cas de multiples diagnostiques d’éligibilité
- Liste des candidatures : Refonte et affichage de la localisation des postes pour les employeurs
- Liste des métiers d’une SIAE : Afficher le nombre de métiers

## [59] - 2023-03-27

### Ajouté

- GEIQ : Permettre à un prescripteur habilité de valider l'éligibilité GEIQ d'un candidat
- GEIQ : Ajout des champs type de contrat et durée hebdomadaire à l’écran de validation d’embauche

### Modifié

- GEIQ : Adaptation du texte de confirmation d’annulation d’embauche

## [58] - 2023-03-13

### Ajouté
- Contrôle a posteriori : l’absence de réponse de l’administration dans les délais impartis implique consentement
- Ajout d'un lien pour modifier ses informations personnelles sur Inclusion Connect
- Ajout d'un bandeau de promotion de RDV-Insertion dans la liste des candidatures des SIAE
- Ajout d'explications pour le motif de refus "L’embauche empêche la réalisation des objectifs du dialogue de gestion"

### Modifié
- Inscription : Rendre la civilité obligatoire pour les candidats
- UI : Amélioration du parcours de gestion des candidatures
- GEIQ : Autoriser la création d'antenne
- Stats : Montrer la popup Tally au maximum une fois toutes les deux semaines
- UI : Autres corrections et améliorations

## [57] - 2023-02-27

### Ajouté
- Contrôle a posteriori : affichage de l'historique des sanctions dans les données d’aide à la décision
- Contrôle a posteriori : application des suspensions d'auto-prescription
- Candidature : bouton désactivé & tooltip pour expliquer qu'on ne peut pas modifier les informations personnelles
- Pré-remplir l'email sur inclusion connect pour un utilisateur voulant activer un compte qui l'est déjà
- Candidature : Ajout de motifs de refus spécifiques aux GEIQ
- Ajout d'une bannière pour migrer les comptes vers Inclusion Connect

### Modifié
- Autocomplétion : augmentation du nombre de résultats affichés pour les communes
- Mise à jour du SIRET associé lors de la réactivation d'une fiche salarié
- UI : Modifications d'accessibilité et de précision de certains messages

## [56] - 2023-02-13

### Ajouté
- Contrôle a posteriori : Affichage de liens vers les justificatifs
- Contrôle a posteriori : Ajout de l'affichage et choix des sanctions
- Parcours d'inscription : Ajout d'une vue d'activation de compte Inclusion Connect
- UI : Export en XLSX au lieu de CSV

### Modifié
- Autocomplétion : modification des règles de gestion de l'autocomplétion de villes
- PASS IAE : Les suspensions à 12 mois sont passées à 36 mois
- Parcours d'inscription : détection de préexistence de candidats à l'inscription
- RGPD : Mise à jour des mentions légales, confidentialité et conditions générales
- UI : Affichage des SIRET des structures sur le tableau de bord
- UI : Modifications d'accessibilité et de précision de certains messages

## [55] - 2023-01-30

### Ajouté

- Automatisation : Mise à jour des villes
- Fiches salarié : ajout d'un bandeau d'information pour les SIAEs ayant une convention active sans annexe financière
- Fiches salarié : ajout des informations d'horodatage ASP
- Parcours d'embauche : Possibilité de renseigner le numéro de sécurité sociale ou la raison de son absence
- UI : Ajout d'un bandeau de promotion de DORA dans le tableau de bord

### Modifié

- Admin : cacher les boutons de validation/refus des habilitations au support externe
- Admin : plus de granularité sur certains messages des PASS IAE et des fiches salarié
- Contrôle a posteriori : Exclusion des SIAE dont le controle est terminé du rappel en phase contradictoire
- Contrôle a posteriori : Notifier les DDETS quand les SIAE attendent les sanctions
- Fiches salarié : Correction pour le message d'information d'actualisation
- Matomo : améliorations de stabilisation
- Metabase : améliorations et corrections diverses
- Recherche de postes : suppression du badge du nombre de postes ouverts si le recrutement est fermé
- Thème : mise à jour vers la version 0.5.7
- UI : Mise à jour de l'URL de la communauté
- UI : amélioration des cartes SIAE
- UI : amélioration des onglets avec résultats des recherches

## [54] - 2023-01-16

### Ajouté
- Admin : Ajout d’un filtre des ZRR par statut
- Candidature : Affichage d’une alerte lorsque les informations personnelles du candidat datent de plusieurs mois, et d’un parcours pour les mettre à jour
- Recherche de postes : Affichage des offres Parcours Emploi Compétences (PEC)

### Modifié
- Candidature : Correction de bugs lors de l’affichage du PASS IAE
- Candidature : Afficher “non renseigné” au lieu de masquer les informations manquantes
- Candidature : Clarification du texte du bouton de dépôt de candidatures
- Connexion : Gestion de l’indisponibilité d’Inclusion Connect à la déconnexion
- Contrôle a posteriori : Exclusion des agréments émis par Pôle Emploi des candidatures à contrôler
- Fiches salarié : Amélioration de performances
- Parcours d’embauche : Correction d’un bug lorsqu’une candidature est ouverte dans plusieurs onglets
- Recherche de postes : Amélioration de la fiche publique entreprise

## [53] - 2022-12-16

### Ajouté
- Analytics : Ajout d'une application d'analytics et de premières métriques sur les fiches salariées
- API : Ajout de l'API candidats à la liste des nouveautés de la doc
- Parcours d'embauche : Ajout d'un message d'erreur quand le NIR renseigné existe déjà
- Parcours d'embauche : Ajout des informations concernant le QPV et le ZRR dans les diagnostics d'éligibilité
- Contrôle a posteriori : Ajout d'une formule de politesse au mail de notification avant la phase contradictoire
- Contrôle a posteriori : Ajout d'accès en lecture dans l'admin
- Contrôle a posteriori : Notifier les SIAE sans justificatifs vers la fin de la phase contradictoire
- Contrôle a posteriori : Clarifier le début de la phase contradictoire dans un mail
- Contrôle a posteriori : Communiquer aux DDETS les SIAEs n'ayant pas répondu en phase amiable
- Contrôle a posteriori : Ajout de notifications lors du passage forcé en phase contradictoire
- Contrôle a posteriori : Ajout d'un export depuis l'admin
- Espace salarié : Ajout de l'espace "Mes salariés" dans le tableau de bord des SIAE
- Facilitateurs : Utiliser inclusion Connect pour créer un compte et se connecter
- Fiches salarié : Ajout de nouvelles villes pour aider la recherche quand plusieurs communes ont le même code INSEE
- Fiches salarié : Ajouter la possibilité de trier les fiches salariées
- Inclusion Connect : Ajout d'une vue pour reprendre la création de compte lorsque l'email de vérification n'arrive pas
- Inclusion Connect : Ajout d'un lien direct pour créer un compte (et non arriver sur la page de connexion)
- Métabase : Ajout des SIAE, Organisations prescriptrices et institutions dans le suivi
- Métabase : Ajout de l'appartenance à une zone qpv pour les candidats
- Métabase : Ajout de données anonymisées sur les utilisateurs
- Métabase : Ajout de la région du prescripteur aux données
- Métabase : Ajout du suivi de la consommation des ETPs
- Métabase : Ajout d'un accès stats pour la DGPE
- Métabase : Ajout de la table FluxIAE Convention
- Métabase : Ajout d'un suivi mensuel de la consommation en ETP des SIAEs
- Recherche de postes : Ajout d'un onglet dans les resultats de recherche employeur pour afficher les fiches de postes
- Recherche de postes : Ajout de filtres par type de contrat
- Recherche de postes : Ajout de filtres par domaine métier ROME
- Sécurité : Mise en place des Content Security Policy
- Sécurité : Mise en place d'un antivirus pour les fichiers déposés dans sur le stockage S3

### Modifié
- Admin : Amélioration des performances de la page de candidatures
- API : Amélioration des performances de l'API des SIAEs
- Candidature : Mise à jour des ROME et appelations
- Candidature : Modification de la largeur de la page dans certaines étapes du canal de candidature
- Candidature : Masquer la modale de confirmation si les formulaires contiennent des erreurs
- Candidature : Amélioration des performances de la page de détail
- Contrôle a posteriori : Recalcul de l’état d’une EvaluatedSiae avant notification de revue
- Fiches salarié : Améliorations de l'interface de saisie de fiche salarié d'actualisation
- Fiches salarié : Fiabiliser l'information affichée dans l'admin
- Fiches salarié : Meilleur affichage des badges
- Inclusion Connect : Correction de la taille des logos des services partenaires sur certains navigateurs
- Liste de candidatures : modification du filtre par critères d'éligibilité
- Métabase : re-essayer les tâches d'export en cas d'erreur
- Métabase : Nombreuses améliorations de performances des différentes tâches d'export
- Métabase : Désanonymisation de champs ID non sensibles.
- Métabase : Refonte du code de l'application pour faciliter les évolutions futures
- Parcours d'embauche : Amélioration de l'expérience utilisateur
- PASS IAE : Affichage du reliquat du pass en nombre de jours
- PASS IAE : Correction de la détection du dernier employeurs quand ne candidature a été créée directement au statut acceptée
- PASS IAE : Correction de la détection du dernier employeurs avec les candidats du stock AI
- PASS IAE : Permettre l'affichade d'un PASS IAE sans candidatures dans l'admin
- PASS IAE : Modification des règles de prolongation
- Recherche de postes : Correction de la recherche quand une SIAE sans département est trouvée
- Recherche de postes : Améliorations des performances
- Sécurité : Ventilation des tâches d'analyse antivirus
- Thème : mise à jour vers la version 0.5.5
- UI : Multiples petits changements d'ergonomie
- UI : Mise à jour des couleurs de badges
- UI : Mise à jour de l'icone de téléchargement
- UI : Utilisation de notre thème pour les tooltips (bulles d'aides)
- UX : Améliorer l'indicateur d'état de téléversement de fichiers
- UX : Améliorer les performances de certains pages du site
- Utilisateurs : Bloquer la modification des informations personnelles dans l'admin d'utilisateurs utilisant un SSO

### Retiré
- Candidature : Suppression du bandeau d'alerte sur l'évolution des critères d'éligibilité
- Fiches de poste : Suppression de la contrainte d'unicité sur les appelation par SIAE
- UI : Suppression du lien (cassé) d'inscription à la newsletter


## [52] - 2022-11-04

### Ajouté
- API : Ajout de l'API candidats
- API : Exposition d'un lien vers la page de la structure sur les emplois pour l'API data.inclusion
- Ajouts divers Metabase (régions, hash du numéro de PASS)
- Candidatures : ajout du motif de refus "dupliqué"
- Contrôle a posteriori : Ajout du parcours de sanctions
- Contrôle a posteriori : Mode lecture seule pour les campagnes terminées
- Fiches salarié : Transmission de la date de fin pour les PASS IAE sans fiches salarié
- Technique : ajout de HTMX

### Modifié
- Contrôle a posteriori : inclusion des AI pour 2022, améliorations d'affichage
- Contrôle a posteriori : les SIAE évaluées sont dans un état finalisé à la clôture de la campagne
- Correction d'affichage diverses
- Exports des rejets d'API PE : ajout du département
- Fiches salarié : vérification de la convention et rafraichissement du SIRET lors d'un clonage
- Metabase : utiliser l'adresse de la structure parente pour les antennes
- Tableau de bord: retrait de la bannière vers le pilotage
- Technique : Améliorations de performance notables (tests, admin, filtres de candidatures)
- Technique : Mise à jour de django, uWSGI & elasticapm

### Retiré
- Siae : retrait du type ACIPHC


## [51] - 2022-10-24

### Ajouté
- Contrôle a posteriori : Nouvelle option pour se retirer de la campagne
- Contrôle a posteriori : Autorise la modification des justificatifs pendant la revue de la phase contradictoire
- Contrôle a posteriori : Mode lecture seule pour les campagnes terminées
- Fiches salarié : Transmission de la date de fin pour les PASS IAE sans fiches salarié
- API : Exposition d'un lien vers la page de la structure sur les emplois pour l'API data.inclusion

### Modifié
- Fiches salarié : La géolocalisation est réalisée à l'étape 2 au lieu de l'étape 1 du parcours
- Correction du formatage du NIR lors du dépôt de candidature
- UI : Ajustement du bandeau Dora dans le tableau de bord
- Inscription : Gestion de l'erreur en cas de changement d'email sur France Connect qui rentre en conflit sur les emplois
- UI : Maj du theme itou vers la v0.5.2
- UI : Initialise les sélecteurs de date JS une fois par page
- UI : Remplacement des ressources JS/CSS servies par CDN par des ressources servies localement.

## [50] - 2022-10-10

### Ajouté
- Fiches salarié : ajout de messages d'information en cas d'erreurs de géolocalisation de l'adresse #1338
- Fiches salarié : nettoyage automatique des fiches salarié sans PASS IAE #1523
- Pilotage : intégration de formulaires Tally sur les vues stats #1522, #1529
- PHC : limite l'accès aux contrats PHC à une liste définie d'ACIs #1520
- PASS IAE : ajout d'une commande pour gérer les rejets d'API PE #1528
- Candidatures : amélioration du parcours de prescription du dépôt de candidatures (étape 3 de la refonte) #1485
- UI : enlève les espaces lors de la présentation d’identifiants #1540
- Inclusion Connect : utiliser Inclusion Connect en tant qu'employeur #1526
- Support : ajout d'une fonctionnalité pour prendre temporairement l'identité d'un utilisateur #1541
- Technique : gestion des settings & secrets #1461, #1567, #1572
- Technique : utilisation de `pip-tools` pour la gestion de dépendances #1507
- Technique : suppression de Typeform et remplacement par Tally #1530
- Technique : utilisation de pytest pour lancer les tests #1554
- Contrôle a posteriori : évaluation SIAE, implémentation de la phase contradictoire #1566
- Contrôle a posteriori : ajout de l’ID des SIAE évaluées aux URLs du contrôle a posteriori #1576
- Contrôle a posteriori : cache les candidatures des campagnes précédentes #1579

### Modifié
- Technique : mise à jour vers Django 4.1 #1453
- Technique : amélioration de la résilience du parcours d'inscription prescripteur face aux API indisponibles #1532
- Technique : correction de l'intégation continue (CI) #1534
- Technique : accélération des tests #1559
- Technique : mise à jour vers Django 4.1.2 # 1588
- Documentation : modification des notes d’installation (Docker, venv, config) #1515, #1517, #1519, #1551
- PASS IAE : affichage du PASS IAE pour les demandeurs d'emploi #1535
- Pilotage : candidatures - ajout du nom du conseiller Pôle emploi #1543
- Pilotage : candidatures par fiche de poste - ajout colonne injection AI #1546
- Pilotage : ajout de colonnes utiles extraites du NIR (sexe, année et mois de naissance) dans la table candidats sur Metabase #1565
- Pilotage : ajout de deux blocs informatifs en bas des pages stats #1565
- Thème : mise à jour vers la version 0.5.1 #1542
- Candidatures : les candidatures ne sont plus toutes enregistrées comme "spontanées" #1548
- Candidatures : nettoyage des vues de l'ancien parcours de dépôt de candidatures #1556
- Prolongation / suspension : le dernier employeur qui a embauché un candidat a la main pour prolonger ou suspendre #1536
- Prolongation / suspension : le motif de suspension “contrat de travail suspendu depuis plus de 15 jours” d'un pass IAE n’empêche plus de postuler à d'autres offres #1539
- UI : notification des données factices sur l'environnement de démo #1530
- UI : lors de la saisie des informations d'un utilisateur, le téléphone devient optionnel et les informations de l'adresse obligatoires #1530
- UI : correction “S’inscrire” dans les options de navigation #1549
- E-mails : vérification de la suppression de l'e-mail de notification d'une nouvelle embauche pour les SIAE #1530
- E-mails : modification de l'e-mail envoyé aux prescripteurs lors d'un refus d'habilitation #1530
- PHC : utiliser le SIRET plutôt que la clé primaire des SIAE pour choisir les contrats convergence #1596
- Fiches salarié : déblocage du parcours des fiches salarié en cas d'absence de type de voie dans l'adresse du salarié #1560
- Tests : corrections de tests #1543, #1550, #1552, #1563, #1533, #1569, #1583, #1591, #1586

### Supprimé
- Candidatures : les réponses données aux candidatures sont supprimées lors d'un transfert entre SIAE #1530
- Prolongation / suspension : suppression de l'affichage de la raison d'une suspension #1530
- Pilotage : désactivation temporaire de certains formulaires Tally #1565
- Pilotage : désactivation temporaire du tableau de bord AF DGEFP #1565
- Pilotage : retrait de plusieurs badges "Nouveaux" # 1565
- Contrôle a posteriori : retrait des dates de la campagne de contrôle a posteriori 2021 #1587

## [49] - 2022-09-12

### Ajouté
- Inclusion Connect : Ajout de variables d'environnement en dev pour Inclusion Connect #1463
- Pilotage : Ajout réseaux structures #1478
- Pilotage : Ouverture nationale des stats PE+Employeur (Le Grand Jour du C2) #1486
- Pilotage : Les DR PE peuvent maintenant voir les stats de toute leur région #1490
- Pilotage : Ajout org_prescripteur pour améliorer le filtre par département ( Update 016_candidatures_recues_par_fiche_de_poste.sql #1492 )
- Pilotage : Ajout org_prescripteur ( 015_Metabase : add column id organization #1494 )
- Pilotage : Taux transformation prescripteurs : ajout département prescripteurs #1495
- Pilotage : cddr_par_fdp : ajout département prescripteur #1497
- Pilotage : delai cddr : ajout departement prescripteur #1499
- Pilotage : candidatures echelle locale : ajout département prescripteur #1501
- Pilotage : Ajout du nom des organismes prescripteurs ( Update 019_candidatures_echelle_locale.sql #1510 )
- Pilotage : Taux de transformation : candidat accepté #1514
- Pilotage : Candidatures : modif ajout du nom du département #1518

### Modifié
- Theme : Maj du theme itou vers la v0.5.0 et du logo du ministère du travail #1491
- Import ASP : Evolutions mineures des imports SIAE et EA, dont évolutions des règles de suppression automatiques de structures #1500
- Inclusion Connect : Améliorations diverses pour inclusion connect #1487
- Pilotage : Petites améliorations mineures métabase (format des Url, ajout de colonnes, tests) #1436
- Pilotage : obtention du bon nombre de fiches de poste #1477
- Fiche Salarié : Modification du modèle des fiches salarié #1468
- Fiche Salarié : Permettre la correction de l'adresse du candidat lors de la création de la fiche salariée #1506
- PASS IAE : ApprovalsWrapper, phase 2 : S'en débarasser totalement. #1450
- PASS IAE : En tant que SIAE je veux m'assurer que l'annulation du PASS est justifiée dans mon cas #1476
- Candidatures - refus : Un bouton radio sans texte #1471
- Candidatures - refus : nouveaux motif de refus / Pilotage #1474
- Candidatures - nouveau parcours : Enregistrement de la date d'expiration du diagnostique d'éligibilité en base de données #1472
- Candidatures - nouveau parcours : Diverses corrections et améliorations #1473
- Contrôle a posteriori : Déplacement des données de contrôle a posteriori pendant un move_siae_data #1479
- Sécurité mots de passe : Améliorations de sécurité diverses #1502
- Admin : Ne pas lever d'erreur 500 dans l'admin quand un NIR existe déjà. #1475
- Technique : Déplacement des types de prescripteurs et des institutions dans des fichiers dédiées pour en améliorer la lecture #1446
- Technique : Mise à jour des dates du passe IAE des fixtures #1480
- Technique : Homogénéiser la construction de l'url du site #1488
- Technique : Mise à jour de django-allauth #1513
- Technique : Ajoute des recettes Docker dans le README #1516
- Tests : Tester en local Itou X Identity Providers ( config: Update default FQDN #1489 )
- Tests : Nettoyage de code de tests #1503
- Tests : Correction d’un test au résultat incertain #1504

### Supprimé
- Pilotage : Abandon de 2 des 4 extracts C2 #1484

## [48] - 2022-08-29

### Ajouté
- Inclusion Connect : ajout du support de la connexion prescripteurs
- Admin : affichage du SIRET de la SIAE d'une candidature
- Contrôle a posteriori : ajout d'un bandeau d'information à propos de pièces manquantes
- Contrôle a posteriori : ajout d'une mention concernant la phase de contrôle actuelle pour plus de clarté
- Technique : ajout d'un script permettant de détecter des doublons parmi des candidats identifiés par l'ASP.
- OpenID Connect : affichage d'un message d'erreur si l'utilisateur a plusieurs types
- Enregistrement utilisateur : s'assurer qu'un seul type soit possible
- Enregistrement utilisateur : demander toutes les informations nécessaires à la création
- Enregistrement utilisateur : ajout d'une étape de retour d'information aux prescripteurs


### Modifié
- Inclusion Connect : corrections diverses (mise à jour keycloak, gestion du "retour", enregistrement prescripteurs, bugs lors de la déconnexion)
- Inclusion Connect : amélioration de l'email d'inscription
- Fiches Salarié : améliorations de stabilité et de performance
- Contrôle a posteriori : ne pas passer en phase contradictoire les SIAE ayant transmis mais non validé leurs pièces
- Contrôle a posteriori : les DDETS peuvent contrôler une SIAE même si toutes les pièces ne sont pas soumises
- Contrôle a posteriori : correction d'un cas où une SIAE pouvait ne pas être en capacité de soumettre ses documents
- Extraction des utilisateurs pour le C2 : Ignorer les SIAEs inactives
- PASS IAE : ne pas passer en délivrance manuelle si le demandeur d'emploi a un NIR
- PASS IAE : créer un PASS automatiquement si aucun agrément Pôle emploi n'est trouvé.
- Candidatures : modifications cosmétiques
- Enregistrement candidat : noter "non enregistré à Pôle emploi" si aucun ID renseigné
- Enregistrement candidat : amélioration d'éventuelles erreurs liées aux sessions
- Utilisateurs : modifications de wording (RQTH, OETH)
- Technique : rendre les erreurs non retirables sur les formulaires
- Technique : mise à jour de Sentry, de Django et du thème Itou
- Technique : simplification de branches de code liées à la présence d'agréments ou PASS IAE
- Technique : permettre la modifcation de la couleur de fond


### Supprimé
- Page de connexion : retrait du message d'accueil


## [47] - 2022-07-29

### Ajouté
- Affichage (puis suppression une semaine plus tard) d'un message informatif concernant l'indisponibilité des fiches salarié.
- Ajout d'un message d'alerte lors d'une suspension pour indiquer la possibilité qu'elle soit levée.
- Ajout d'une option de « preflight » pour les _management commands_ des fiches salarié.
- Ajout du lien vers le formulaire de suspension pour les prescripteurs habilités.
- Ajout de trois champs au CSV `hard_duplicates_{env}` : NIR, date de naissance et lien vers les candidatures de moins de trois mois.
- API : ajout des données « PrescriberOrganization » à la vue d'API pour data.inclusion.


### Modifié
- Inclusion Connect : correction d'un bug qui empêchait la déconnexion.
- Correction d'erreurs pickle récurrentes qui déstabilisaient la CI.
- Montée de version de Python vers la 3.10 dans tous nos environnements et mise à jour des dépendances.
- La vérification du NIR pendant le parcours de candidature ne prend plus en compte la casse pour éviter de créer des doublons.
- Mise à jour du message envoyé au prescripteur quand une demande de prolongation est faite.
- Mise à jour de la librairie `django-extensions-plus` en local pour corriger un bug apparu avec Python 3.10.
- Correction d'un bug : affichage sur le tableau de bord des prescripteurs des candidatures masquées par l'employeur.
- Import SIAE : résolution d'un bug (structure active mais dont le conventionnement a été soudainement retiré).

## [46] - 2022-07-15

### Ajouté
- Lancement d'Inclusion Connect pour les prescripteurs !
- La suspension est supprimée si la date de début de contrat est égale à la date de début de suspension du PASS IAE
- Évolution des stats employeur : "Ensemblier" des structures
- Ajout d'un message pour informer l'employeur lorsque l'adresse de son entreprise est erronée.
- Conservation du NIR lors de l'inscription avec France Connect
- Active l'authentification par jeton pour `data.inclusion`
- Pilotage : ajout d'une colonne "Nom complet de la structure" sur les candidatures dans Metabase
- Ajout d'un mécanisme de contrôle d'unicité des UUID des organisations (`OrganizationAbstract`)

### Modifié
- Controle a posteriori : correction de l'anomalie en phase contradictoire qui permettait à la SIAE et à la DDETS de mettre à jour en même temps.
- Correction de l'étape de saisie du mail du candidat pour les employeurs et les prescripteurs
- Ajustement de la taille de la bannière BETA
- Mise à jour de Django vers la version 4.0.6
- Amélioration de l'historisation des changements de champs d'utilisateurs via les SSO
- Correction de la déconnexion des utilisateurs anonymes
- Contrôle a posteriori : ajout de labels plus explicites pour les DDETS en phase contradictoire
- Pilotage : ajout d'une requête "suivi des visiteurs"

## [45] - 2022-07-01

### Ajouté
- Affichage de l'identifiant obfusqué de l'utilisateur dans l'administration
- Page de statut pour API externes
- Bloquer la création d'antennes pour les EA / EATT / GEIQ
- Pilotage : ajout du taux d'acceptation des candidats orientés par prescripteur
- Affichage d'un message d'appel à contribution Dora
- Ajout d'une tâche planifiée d'envoi des PASS IAE à Pôle emploi
- Ajout d'une tâche planifiée pour envoyer les agréments Pôle emploi à Pôle emploi
- API : ajout d'une vue pour représenter les SIAE au format data.inclusion
- Controle a posteriori : sujet et objet d'un email d'info aux SIAE
- Controle a posteriori : phase contradictoire
- Envoyer un email automatique lorsqu'une une nouvelle structure est détectée après l'import de nouvelle SIAE

### Modifié
- Amélioration de l'UX de l'étape de renseignement du NIR du candidat dans le parcours de prescription
- Déconnexion de PE Connect via une redirection et non via le serveur
- Mise à jour des fiches de poste en difficulté de recrutement
- Seconde refonte du client d'API Pôle emploi
- Controle a posteriori : clôture des campagnes, amélioration de l'admin et notifications emails
- Correction du lien « questions à la communauté » dans le pied de page
- Mise à jour de la zone de contenu d'aide sur les pages « Stats »
- Technique : commandes _venv du Makefile et logs SQL en double / Utilisation de factory.Trait pour SiaeFactory()
- Mise à jour du thème ITOU vers la version 0.4.5
- Ignorer les types exotiques comme ACIPA pendant l'import SIAE

## [44] - 2022-06-19

### Ajouté
- Pole Emploi API : Migration des logs (étape 1/3)
- Pole Emploi API : Réécriture du client d'API (étape 2/3)
- Transfert des candidatures entre SIAE
- Ajout de stats pour les agents PE
- Pilotage : Calculer le délai entre la première candidature et la première embauche pour les candidats orientés par PE
- Pilotage : Ajout du type de structure pour permettre l'ajout d'un filtre associé
- Pilotage : Suivi du taux de refus par type de structure
- Pilotage : Suivre le délai de recrutement des candidats en IAE
- Pilotage : Suivi du nombre de candidats sans solution à 30 jours
- Inclusion Connect : Factorisation des modèles de FranceConnect, ajout des modèles d'Inclusion Connect et ajout de tests (étape 1/3)

### Modifié
- Contrôle a posteriori : laisser le formulaire de saisie du commentaire modifiable après la revue par les DDETS
- Controle a posteriori : afficher la date du Pass IAE
- Controle a posteriori : email d'information aux siaes de la campagne 2021 partie 2
- Gérer mes fiches salarié : rendre visible les fiches à l'état 'nouvelle'
- Correctif pour débloquer les prescripteurs n'ayant pas la possibilité de mettre à jour le NIR
- En tant qu’employeur je veux valider l’embauche d’un candidat dans le tableau de bord de la bonne structure. Ajout d'une modale de confirmation contenant la carte de la structure lors de l’embauche.
- Contextualiser les contrats proposés lors de l’enregistrement d’une fiche de poste
- Une SIAE doit pouvoir réactiver une fiche salarié qu'elle a désactivée
- Technique : accélération de la CI ; mise à jour des Github Actions et des paquets Python de dev ; éviter l'arrêt du serveur en environnement de développement Docker ; améliorations de la configuration VSCode et de la documentation ; ne pas nécessiter Redis en développement local ; amélioration de la performance du cron Metabase quotidien

### Supprimé
- Retirer le message sur le tableau de bord indiquant que le transfert de fiches salarié est interrompu
- Supprimer le message d’information sur les régularisations AI qui est affiché dans leur tableau de bord

## [43] - 2022-06-02

### Ajouté
- Contrôle a posteriori, Pack DDETS : formulaire de saisie du commentaire
- Contrôle a posteriori, Pack DDETS : valider les SIAE en fin de contrôle de leurs autoprescriptions
- Contrôle a posteriori, Pack DDETS : formulaire de validation des critères administratifs sélectionnés pour une autoprescription
- Possibilité de désactiver les fiches salarié
- Déploiement progressif des stats PE et employeur
- Procédure pour l'envoi des notifications de MAJ des fiches salarié à l'ASP
- Procédure de reprise des données de l'ASP pour les notifications de changement sur les PASS IAE
- Mécanisme d'étranglement pour l'API fiche salarié.
### Modifié
- Correction des carousels de bienvenue pour la version mobile
- Nouvelle interface pour les résultats de recherche employeurs
- Contrôle a posteriori, Pack SIAE : Rattrapage des SIAE ayant réalisé entre 2 et 9 autoprescriptions
- Plus de mention du PASS IAE dans les emails reçus par les employeurs non soumis aux règles d’éligibilité IAE
- Mise à jour des scripts de transfert des fiches salarié
- Mise à jour du theme itou vers la v0.3.9
- Pilotage : Parmi les fiches de poste en difficulté de recrutement, calculer le nombre de fiches de poste n'ayant jamais reçu de candidatures
- Pilotage : Ajout d'informations afin d'avoir des filtres à l'échelle locale
- Correction d'erreurs dans le parcours d'inscription candidat
- Optimisation des performances SQL pour l'API fiches salarié
- Optimisation des performances (dans certain cas) dans le parcours d'inscription
- Remplacement de l'API pour la récupération des informations des entreprises

## [42] - 2022-05-13

### Ajouté
- Ajout d'un champ manquant dans les fiches de postes pour les OPCS
- Ajout de stats PE qui permettent à tout membre d'agence PE de consulter les stats de son département (fonctionnalité cachée en attente de déploiement)
- Ajout de champs de recherche pour l'API fiches salarié
- Message d'information sur la mise en place de l'assistance technique par téléphone
- Contrôle a posteriori : phase enrichissement des données
- Contrôle a posteriori, Pack SIAE : notification et liste des justificatifs demandés (cartes 1 à 3)
- Contrôle a posteriori, Pack SIAE : sélection et enregistrement des critères à justifier (carte 4)
- Ajout du champs "origine détaillée" dans l'export Metabase pour créer un filtre (TB 160)
- Contrôle a posteriori, Pack SIAE : dépôt des pièces justificatives (carte 5)
- Contrôle a posteriori, Pack SIAE : soumission des justificatifs (carte 6)
- Contrôle a posteriori, Pack DDETS : notification ouverture de la phase de transmission des justificatifs (carte 1/5)
- Contrôle a posteriori, Pack DDETS : liste des siae contrôlées (carte 2/5)
- Fonctionnalités techniques permettant de notifier l'ASP des modifications de date de début ou de fin d'un PASS IAE rattaché à une fiche salarié.
- Droits d'administration sur les candidatures et les fiches salariées
- Contrôle a posteriori, Pack DDETS : liste des autoprescriptions contrôlées pour une Siae (carte 3/5)
- Améliorer la visibilité en affichant le nom de la structure dans l'entête

### Modifié
- Remplacer les icônes Feather par icônes Remix
- Amélioration de la commande d'envoi du stock de PASS IAE à Pôle emploi
- Modification du critère d’éligibilité réfugié
- Ajustement de la mise en page d'un message d'alerte dans le processus d'éligbilité
- Ajustement de l'agencement de certaines pages de connexion/création de compte
- Reformulation de "données IAE" sur les statistiques Pôle emploi pour "fiches de poste en tension"
- Ajout d'une colonne "DateRattachement" dans l'extract des utilisateurs C2
- Mise à jour du theme itou vers la v0.3.8
- Correction technique sur les tests unitaires pour éviter les erreurs d'unicité aléatoires
- Prise en compte d'un nouveau référentiel dans le FluxIAE dans l'import ASP des SIAE
- Rendre plus robuste le code de l'API Pole Emploi le temps de l'envoi des PASS IAE
- Correction de la recherche d'agréments Pôle emploi par NIR
- Correction technique du chargement des villes en base de données
- Correction d'un cas particulier sur les conventions dans l'import ASP des SIAE
- Correction des erreurs d'accessibilité sur les tableaux et les scripts
- Correction d'un bug lorsqu'un PASS IAE existe déjà pour le même NIR ou ID Pôle emploi
- Résolutions d'erreurs diverses dans FranceConnect

### Supprimé
- Champ en double dans le modèle des fiches de poste

## [41] - 2022-04-22

### Ajouté
- Refus de la connexion Django pour les utilisateurs SSO
- Ajout du fournisseur d'identité Inclusion Connect dans IdentityProvider
- PASS IAE : retrait de PDFShift et affichage une page HTML prête à imprimer
- Ajout d'un comportement dynamique sur le champ "Autre type de contrat" dans le formulaire des fiches de poste
- Ajout d'une page de connexion générique reprenant les différents types de profils utilisateur
- Affichage du bon message d'erreur aux utilisateurs de PE Connect qui utilisent le formulaire Django
- Ajout d'une Github Action pour Metabase
- Ajout d'une seconde vue stats "Facilitation de l'embauche" pour les DREETS
- Ajout des notifications de modifications du PASS IAE pour l'ASP - modèles et sérialiseurs
- Ajout de custom URLs Matomo sur toutes les stats.

### Modifié
- Mise à jour vers Django 4.0.4
- Correction de tests unitaires instables (suspension et fiche salarié)
- Synchronisation du groupe de permissions du support externe
- Correction de la fixture PE Approvals
- Correction du script d'import des SIAE
- Correction d'une erreur de sérialisation de l'adresse de l'employé
- Correction d'une erreur dans le message de confirmation aux DDETS lors de la sélection du ratio.
- Correction d'une régression concernant les dates de suspensions
- Modification et ajout d'information concernant la commande d'import des agréments Pôle emploi

### Supprimé
- Retrait des mentions à la DGEFP sur le dashboard
- Retrait des imports de données `external-data` des remontées d'erreur sur Sentry

## [40] - 2022-04-08

### Ajouté
- Ajout du premier lot de fonctionnalités concernant le contrôle a posteriori
- API Fiche de poste: ajout d'un paramètre d'état
- Stats: ajout de `siae_hiring`, renommage de `stats_siae` en `states_siae_etp`
- Refonte globale des filtres externes de l'interface (en particulier pour les candidatures)

### Modifié
- Analyses: mises à jour des exports de saisies mensuelles, sorites, etp par salarié, recrutements et candidatures reçues
- Stats: amélioration des envois à Matomo
- Thème: mise à jour du thème ITOU en 0.3.4
- Technique: Correction d'une régression affectant nos tâches planifiées
- Technique: Améliorations concernant l'affichage de champs de lieux dans l'administration
- Technique: refonte des sorties standard dans les commandes Django
- Technique: modification de la notation des paramètres de l'API Pole Emploi
- Technique: réparer l'import du fichier des villes
- Correction de la redirection de l'utilisateur dans les formulaires à plusieurs étapes des fiches de poste
- Correction d'un problème de concurrence lors de l'attribution de numéros de PASS IAE
- Modification des termes "DIRECCTE" par "DDETS"
- Modifications graphiques mineures concernant les badges et les sources de données
- Amélioration du script de déplacement de SIAE vers une autre
- Amélioration du script d'import de données d'agréments PE
- Amélioration notable des performances de l'interface d'administration

### Supprimé
- Retrait du code associé aux prolongations pour confinement


## [39] - 2022-03-25

### Ajouté
- Exports de données SQL : Ajout du nombre de candidatures par structure
- Technique : Ajout d'une route temporaire pour tester les custom URLs Matomo
- Ajout d'un nouveau tableau de bord "Facilitation de l'embauche" pour les DDETS
- Ajout de l’import des NIR/NTT/NIA à partir des données ASP
- Ajout d'un script d'extraction des utilisateurs C2 du C1
- Mise à jour des liens vers communaute.inclusion.beta.gouv.fr
- API Pole emploi : Ajout de journaux et de vérifications supplémentaires
- API Pole emploi : Ajout d'un script d'export de tous les Pass IAE
- Refonte (UI, UX) des fiches de poste avec un nouveau parcours et de nombreuses nouvelles options
- Facilitateurs : Support des fiches de poste

### Modifié
- Tableau de bord : Rendre les menus déroulants défilants quand ils contiennent trop d'éléments
- Tableau de bord : Affichage des fiches salarié nécessitant intervention
- SSO: Identification des utilisateurs s'étant connecté avec FranceConnect
- Cron quotidien Metabase : améliorations diverses (performance, fonctionnalités, lancement plus tôt)
- API Pole emploi : Correction des erreurs occasionnelles sur la recherche d’agréments

### Supprimé
- néant

## [38] - 2022-03-11

### Ajouté

- Commande de fusion des agréments Pôle Emploi
- Dans l’administration, il est désormais possible :
  - De trouver une convention via son ID ASP
  - D’exporter des SIAEs
  - De visualiser le statut de la fiche salarié sur les PASS IAE (gestion du cas d’une fiche existante pour un même PASS IAE dans la même SIAE)
- Affichage du nombre de fiches salarié à traiter sur le tableau de bord
- Gestion des candidatures liées à des fiches de poste en doublon dans la migration de toutes les données d’une SIAE
- Ajout du parcours d’inscription pour les facilitateurs, affichage et export (sous paramètre, donc désactivé en production)

### Modifié

- Import ASP :
  - Redirection de la sortie dans un fichier pour conserver les informations d’exécution
  - Ajout de la date de désactivation des conventions non actives
  - Améliorations mineures (performance et gestion d’un cas particulier)
- La date de fin de contrat est désormais optionnelle (dans le formulaire d’embauche et celui d’édition des dates de contrat)
- Mise à jour du thème ITOU vers la v3.0.1
- Mise à jour Django vers la 4.0.3
- Correction de quelques erreurs de formatage ou de structure du DOM (arborescence du code HTML)
- Correction des erreurs d’accessibilité sur :
  - Le contraste de couleurs, la présentation et consultation de l’information
  - La structuration de documents et des titres
  - Les formulaires
  - Les éléments obligatoires
- Remplacement des icônes SVG du tableau de bord par les icônes `remixicon`
- API Pôle Emploi :
  - Ajout de logs et de vérifications concernant les erreurs de déchiffrement
  - Ajout de logs d’infos d’environnement dans l’API Pôle Emploi
  - Correctif pour les appels à l’API
  - Correction de l’erreur de déchiffrement lors des appels à l’API
  - Log des jetons lors des appels à l’API
- Correction des tests sur les dates de fin de contrats optionnelles
- Correction des erreurs occasionnelles sur la recherche d’agréments
- Evolutions Metabase :
  - Les fiches de poste des SIAE inactives ne sont plus envoyées.
  - Les candidatures avec une SIAE destinatrice inactive ne sont plus envoyées
  - Les liaisons fiche de poste / candidature portant sur une candidature avec une SIAE destinatrice inactive ne sont plus envoyées
  - Note : les SIAE inactives n’étaient déjà pas envoyées
- Séparation des routes d’authentification en fonction du type de l’utilisateur
- Le titre "Candidature spontanée" a été remplacé par "Déclarer une embauche" sur les pages concernées
- Le lien "Préférences" devient "Mes notifications"

### Supprimé

- Les liens vers "Prolonger/suspendre un agrément Pôle Emploi" et "Candidature spontanée" sont retirés du tableau de bord pour les EA/EATT/GEIQ/Facilitateurs

## [37] - 2022-02-25

### Ajouté

 - Demander et afficher le nombre de postes sur les fiches de postes
 - Ajout d'un champ de texte libre dans certains objets de l'admin
 - Préparation de l’envoi quotidien des PASS à Pole Emploi
 - Création de fiches structure en plusieurs étapes

### Modifié

Métier:

 - Retirer le bouton "je n'ai pas besoin d'aide au poste"
 - Admin: Gestion du status "fiche salarié en attente" dans la page "Pass IAE"
 - Admin: Demander l'organisation prescriptrice seulement si le prescripteur est lié à une organisation
 - Admin: mise à jour de l’email utilisateur, message d'erreur si l'email est déjà utilisé

Front:

 - Correction des erreurs a11y sur les tableaux
 - Correction des erreurs a11y sur les scripts
 - Mise a jour du theme itou vers la v0.2.7
 - Petits changements dans l’écran "Description de SIAE"

Bugfixes:

 - Correctif pour permettre de nouveau l'envoi de candidature
 - Niveau de log de certaines erreurs lors du transfert de fiches salarié
 - Un bug empechait de créer une suspension pour les agrément PE qui ont été migrés en PASS IAE lorsque la date de départ manquait
 - Utilisation des noms au format prévu par l’API Pole Emploi
 - La date d’embauche est optionnelle et ne doit pas faire planter l’admin
 - ResumeFormMixin: ensure the resume_link will stay optional

Sécurité:

 - Forcer les CV à être hébergés dans notre Cloud
 - Ajout de la directive HSTS (sur 1H pour commencer)

Technique:

 - Montée de version du client Postgres dans le container django
 - Appliquer djhtml systématiquement

## [36] - 2022-02-13

### Ajouté

- Ajout de la possibilité d’effectuer une recherche par email dans les logs d’erreurs
- Ajout de contrôle dans le formulaire de suspension sur la date de départ des suspensions
- Ajout d'une date de suspension de PASS IAE par défaut
- Ajout de nouvelles stats pour la DGEFP : stats annexes financières, stats contrôle a posteriori.
- Ajout du NIR, NIA ou NTT dans les agréments Pole Emploi
- Ajout de contrôles de cohérence sur la reprise de candidatures via l'interface admin

### Modifié

- Modification de la cohérence de la date de départ des suspensions
- Modification du contrôle de la dernière embauche pour les suspensions
- Modification du niveau de logs par défaut de l'application
- Permettre le téléchargement des pass IAE dans les environnement de validation et de démonstration
- Mise à jour de l'adresse email de contact
- Montée de version du framework Django suite à une mise à jour de sécurité
- Petites améliorations de la documentation, du script de déploiement, et du `Makefile`
- Réactivation du téléchargement des PASS IAE
- Enrichissement des logs du traitement de migration des données d'une SIAE
- Montée de version du moteur de base de données
- Mise à jour du script des annexes financières pour 2022
- Mise à jour du script qui alimente le suivi de la consommation des ETP
- Mise à jour du lien retour dans la fiche candidature pour conserver les filtres de recherche
- Mise à jour du thème de l'application pour préparer les corrections liées à l'audit d'accessibilité

### Supprimé

- Suppression d'un message d'information en double dans le tableau de bord

## [35] - 2022-02-01

### Ajouté

- Ajout de deux nouveaux motifs de suspension d'un PASS IAE dont un uniquement pour les ACI et EI (Contrat Passerelle).
- Ajout de documentation dans le fichier `Makefile`.
- Ajout d'un second tableau de bord pour les DDETS.
- Ajout de la date de naissance dans l'affichage en liste des PASS IAE et des utilisateurs (admin).
- L'affichage des recrutements est en 2 parties, avec une option pour montrer la totalité des éléments (recherche de SIAE).

### Modifié

- Modification de l'admin Django pour ajouter plus de visibilité pour les élément `checkbox` et `radio`.
- Le bouton "Besoin d'aide" envoie dorénavant vers une page d'aide du pilotage et non des emplois depuis une page stats.
- Modification du niveau de log de Sentry.
- Réduction du niveau de log pour l'envoi d'e-mails.
- Modification de la date de mise en production des fiches salarié.
- Modification de l'indexation Google pour les emplois (route `/robots.txt`).
- Modification du `Makefile` concernant le déploiement en production (script `deploy.sh`).
- Modification des marges pour les boutons de connexion.
- Modification des horaires de transfert des fiches salarié.
- Corrections mineures (typos).

## [34] - 2022-01-14

### Ajouté

- Ajout d'un script permettant de transférer les canditatures entre SIAE.
- Ajout d'un message d'information sur la validité des annexes financières.

### Modifié

- Correction d'une erreur de calcul de dates pour les années bissextiles.
- Mise à jour vers Django 4.0.1.
- Correctif dans l'administration des invitations.
- Correctif permettant aux EA et GEIQ de pouvoir à nouveau créer des antennes pour leurs structures.
- Configuration de la connexion avec les serveurs SFTP de l'ASP et mise à jour de `paramiko`.

## [33] - 2021-12-30

### Ajouté

- Ajout de la possibilité de se connecter par France Connect.
- Intégration d'un fichier complémentaire de 50 000 contrats AI en plus des 36 000 contrats déjà traités précédemment.
- Import des GEIQ avec ajout de 4 nouvelles structures. Le dernier import datait d'il y a 12 mois.
- Ajout d'un bouton « Exporter » à la page qui liste les candidatures.
- Ajout d'un message informatif à destination des AI pour les accompagner pendant la reprise de stock.
- Ajout d'un message informatif à destination des AI à propos de la bascule automatique des salariés embauchés en AI avant le 01/12/2021.
- Pôle emploi est maintenant notifié lorsqu'un PASS IAE est accepté.
- Ajout de la permission de lever une suspension au moment de l'embauche.

### Modifié

- La restriction à 30 jours pour les suspensions ne s'applique plus aux administrateurs.
- Il est maintenant possible de candidater même si un PASS IAE est suspendu.
- Résolution d'une incohérence entre la rétroactivité à 30 jours des suspensions et la date de création.
- Résolution d'un bug qui faisait qu'une même candidature apparaissait plusieurs fois dans la liste des résultats.
- On considère dorénavant une éligibilité valide si un PASS IAE valide existe sans diagnostic afin de ne pas forcer les SIAE à repasser par la case « Valider les critères d'éligibilité » pour une nouvelle embauche d'un candidat qui dispose d'un PASS IAE hérité de l'import des AI.
- La création de fiche salarié est maintenant bloquable directement au niveau des candidatures et non plus des PASS IAE.
- Les SIAE peuvent maintenant déclarer leur fiche salarié sans attendre le délai des 96h après l'embauche.
- Mise à jour de la page de conformité concernant l'accessibilité.
- Automatisation de la gestion de la crise du manque d'annexes financières en début d'année : les déconventionnements s'interrompent chaque 1er janvier et reprennent d'eux-mêmes quelques mois plus tard une fois que 95% des conventions ont bien leur annexe financière pour la nouvelle année.
- Réinitialisation du secret d'intégration des tableaux de bord C2 dans le C1 suite à la faille Log4j.
- Résolution d'un bug qui faisait que le lien de suspension d'un PASS IAE manquait à l'appel.
- Correctif sur le lien montré au candidat pour se renseigner sur le numéro de sécurité sociale.
- Correctif du contrôle du NIR dans le rare cas où le mois de naissance n'est pas connu : les mois de naissance fictifs 20 à 30 ou 50 ou plus caractérisent le NIR d'une personne inscrite sur la base d'une pièce d'état civil ne précisant pas le mois de naissance.
- Mise à jour technique vers Django 4.0.
- Mise à jour de la [page statistiques](https://emplois.inclusion.beta.gouv.fr/stats).
- Correctif du message montré aux employeurs non administrateurs dans le cas d'une géolocalisation incorrecte de la structure.
- Le support des emplois ne peut plus modifier les dates d'un PASS IAE si la fiche salarié associée est déjà envoyée ou intégrée.

### Supprimé

- Suppresion du message spécifique aux utilisateurs du logiciel GTA sur le tableau de bord des AI.
- Suppression des PASS IAE refusés et des PASS IAE avec une date dans le futur des notifications pour Pôle emploi.
- Suppression de la page de statistiques avancées.

## [32] - 2021-12-02

### Ajouté

- Ajout d'un profil de démo pour les AI.
- Ajout du nom de la structure prescripteur dans l'export des candidatures.
- Ajout d'un mécanisme d'import de salarié ASP (AI) vers la plateforme.
- Ajout du NIR à l'API "fiche salarié".
- Ajout d'une vérification du type de SIAE pour contrôler les doublons de fiches salarié.
- Affichage dans l'admin du statut de la fiche salarié dans la page PASS IAE.
- Ajout d'un texte explicatif au champ « fin de contrat » pour indiquer « 12 mois » pour les suspensions.
- Envoi à l'ASP d'un fichier contenant des informations sur les PASS délivrés pour les AI.
- Ajout de la possibilité aux employeurs de récupérer un agrément expiré depuis moins de 3 mois dans le module « Prolonger ou suspendre un agrément Pole Emploi ».
- Ouverture des stats employeur à quelques SIAE expérimentatrices.
- Ajout d'un texte statique en bas des pages de statistiques Metabase.
- Mise en place de la limite de la rétroactivité des suspensions à 30 jours avant la date du jour.
- Répertoriage des candidats sans solution à 45 jours.

### Modifié

- Augmentation de la mémoire disponible pour le conteneur PostgreSQL en environnement de développement local.
- Résolution d'un bug dans la délivrance de PASS IAE.
- Résolution d'une erreur 500 quand un employeur tente d'obtenir un PASS IAE pour un candidat en doublon.
- Amélioration des liens des Emplois vers le Pilotage.
- Correctif orthographique de `Organisation délégataire d'un CD` et `CAF - Caisse d'allocations familiales`.
- Le support peut à nouveau modifier le numéro d'un PASS IAE tant que le nouveau numéro ne commence pas par `99999`.
- Renommage du lien « Obtenir un PASS IAE (candidature spontanée) » en « Déclarer une embauche ».
- Renommage du bouton « Je l'embauche et j'obtiens un PASS IAE » en « Oui, j'ai besoin d'une aide au poste ».

### Supprimé

- Suppression du motif de prolongation « Contexte sanitaire » le 1er décembre.

## [31] - 2021-11-18

### Ajouté

- Nouveau motif de refus de candidature : « Candidature pas assez renseignée ».
- Ajout du champ `create_employee_record` sur `Approval` (PASS IAE) afin d'empêcher la création automatique de fiches salarié. Non visible dans l'admin Django.
- Nouvelle page de statistiques chargée dans une iframe.
- Ajout des champs e-mail et téléphone dans l'API fiches salarié.

### Modifié

- Réparation : les candidats autonomes qui ont un compte en double (dont un avec un NIR) peuvent de nouveau candidater. Ils voient un message d'erreur les invitant à se reconnecter.
- Réparation : le mécanisme de mise à jour quotidien des données de Metabase fonctionne de nouveau.
- Réparation : les employeurs peuvent ajouter deux métiers identiques à leur SIAE.
- Réactivation du script d'import des EA dans celui qui est lancé hebdomadairement par Supportix.
- Les durées maximales des prolongations (différentes selon le motif) ont été modifiées.
- Corrections d'erreurs diverses liées aux fiches salarié.
- Pendant l'enregistrement des fiches salarié, la sélection d'une annexe financière est désormais optionnelle.
- Mise à jour de l'URL du portail assistance : il pointe désormais vers la Communauté.
- Prise en compte du NIR dans le script de déduplication des candidats.
- Gestion plus propre des logs des doublons avec export en CSV pour faciliter la vie de Supportix.
- Mise à jour vers Django 3.2.9.

### Supprimé

- Suppression des contrôles sur la date de fin d'embauche et la durée maximum d'un PASS IAE.

## [30] - 2021-11-05

### Ajouté

- Ajout du NIR aux informations du candidat, pour mieux qualifier les comptes candidat
- On peut désormais avoir un aperçu dans le moteur de recherche des modifications dans "Gérer les métiers et recrutements"
- Ajout d'un message dans la déclaration de fiches salarié à l'ASP, on informe désormais les employeurs qu'ils doivent avoir une annexe financière valide pour pouvoir déclarer une fiche salarié dans les emplois
- Un PASS IAE peut dorénavant être prolongé jusqu'à 3 mois après sa fin
- Ajout de la fonctionnalité à certains employeurs pour voir les statistiques Metabase de leurs SIAE
- Les employeurs peuvent prolonger un PASS IAE sans l'avis d'un prescripteur habilité pour deux motifs _CDI conclu avec une personne âgée de + de 57 ans_ et _Fin de formation_
- Admin des diagnostics
  - Permettre la recherche par PK
- Admin des utilisateurs
  - Permettre la recherche par NIR
  - Correctif sur le champ notifications au niveau des structures qui étaient éditable sans raison et prenaient trop de place
  - Correctif sur l'ajout de nouvelles memberships qui n'était pas possible (structures+organisations+institutions) car le champ PK n'était pas éditable
  - Correctif sur le champ "modifié par" au niveau des institutions qui était éditable sans raison
- Admin des conventions
  - Montrer l'ID ASP de structure ASP

### Modifié

- Simplification du tunnel d'inscription des prescripteurs, tout en limitant les doublons
- Correction du test de validité des communes de naissance dans le formulaire de déclaration de fiches salarié à l'ASP
- Amélioration de la visibilité dans la recherche :
  - Des métiers ouverts au recrutement
  - Des structurent qui sont ouvertes au recrutement en candidatures spontanées
  - Redirection des liens de [la communauté](https://communaute.inclusion.beta.gouv.fr) vers [la nouvelle plateforme](https://forum.inclusion.beta.gouv.fr)
- Admin des structures :
  - Correctif sur le champ notifications qui étaient éditable sans raison et prenaient trop de place
  - Correctif sur les fiches de poste : les champs "date de création" et "date de modification" ne sont plus éditables
  - Renommage du nom de la configuration des cronjobs qui passe de `c1-prod-config` à `c1-fast-machine-config`
  - Clarification de la documentation pour les paramètres d'utilisation d'API de pôle emploi
  - Remise de la fonctionnalité de modification des mots de passe utilisateurs depuis l'interface d'admin
- Environnement de développement
  - Résolutions des erreurs de l'agent Elastic APM qui permet de suivre les performances de l'application
  - Correctif des tests concernant la génération du NIR
  - Correctif des données de l'environnement de tests des utilisateurs

### Supprimé

- Suppression du menu "Bloquer les nouvelles candidatures" dans le tableau de bord. Il est déplacé dans le menu "Gérer les métiers et recrutements", anciennement nommé "Publier/gérer les fiches de postes"

## [29] - 2021-10-22

### Ajouté

- Import automatique du NIR à partir de données fournies par l'ASP pour une partie des demandeurs d'emploi (environ 50K)
- Possibilité de passer des classes CSS arbitraires au composant `datepicker`
- Script d'import du thème de l'inclusion permettant de réduire les opérations manuelles
- Fiches salarié :
    - Ajout d’une commande permettant de corriger les fiches salarié qui restaient en erreur sur le SFTP de l'ASP
- Pilotage de l’inclusion :
    - Ajout d'une colonne Metabase `candidats.type_inscription`
    - Ajout de stats DREETS : chaque DREETS peut voir seulemement sa région
    - Ajout de stats DGEFP : la DGEFP peut voir toutes les régions
    - Ajout d'un contrôle de cohérence entre la date de naissance du salarié et les codes INSEE existant à cette période
- Création d'un environnement de recette temporaire destiné aux tests d'intrusion avec des comptes utilisateurs spécifiques

### Modifié

- Rétabissement de la base de données de *staging* qui était cassée
- Fiches salarié :
    - Correction d'un bug possible lors de la reprise de données
    - Le numéro de téléphone et l'email des candidats ne sont plus envoyés à l'ASP
    - La taille du champ `EmployeeRecord.asp_processing_label` passe de `100` à `200` caractères
    - Possibilité de saisir manuellement une adresse en cas de géolocalisation préalable imparfaite
    - Corrections graphiques liées au changement du thème
- Prévention de quelques erreurs de manipulation du support
- Interface d’administration:
    - Correctif pour un bug (erreur 500) qui empêchait la création de comptes demandeurs d'emploi quand `approvals_wrapper` était vide
    - Possibilité de gérer les adhésions depuis la page admin des utilisateurs
    - Un utilisateur ne peut avoir qu'un seul rôle à la fois parmi candidat, prescripteur, employeur ou inspecteur
    - Un candidat ayant déjà un PASS IAE ne peut plus être converti en un autre rôle (prescripteur etc.)
    - Ajout des droits pour que le *staff* puisse manipuler les institutions
- Correction d’un test qui échouait aléatoirement à déterminer la meilleure cible de la fusion de doublons candidats (*Pull request* #931)
- Résolution des problèmes de versions dans les machines créées à la volée en spécifiant explicitement la version de Python cible (*Pull request* #927)
- Interface "Mes Annexes financières" (*Pull request* #909)
    - On montre une AF par groupe d'AF avec le même préfixe
    - Pour chaque groupe, on montre la plus pertinente (soit une AF active, soit une AF récente)
- Pilotage de l’inclusion :
    - Suppression de colonnes obsolètes `fluxIAE_Structure.itou_*`
    - Suppression du rôle stats VIP
    - Prévention d'une boucle d'import potentielle entre `User` et `Institution`
    - Simplification des paramètres de `user.can_view_stats_*`
    - Restriction des stats DDETS aux 4 départements d'expérimentation
- Correctif pour `make test` qui ne permettait plus de spécifier la série spécifique de tests à réaliser
- Affichage d’un texte à destination des SIAE concernant les fiches salarié
- Affichage d’un texte pour préciser la fonction de l’import prolongation/suspension

### Supprimé

- Fiches salarié :
    - Suppression des doublons dans la liste d'autocomplétion des communes INSEE
- Suppression de la commande de management `fix_missing_job_applications_sender` qui corrigeait un problème de candidatures sans émetteur introduit par `deduplicate_job_seekers`
- Suppression des avertissements dans la sortie des tests locaux et dans l'intégration continue

## [28] - 2021-10-08

### Ajouté

- Fiches salarié :
    - Message explicatif sur le délai de 96H : "*Les candidatures acceptées ne seront visibles qu'après échéance du délai d'annulation de 96H*"
    - Gestion des communes dans l'admin
    - Action dans l'admin pour envoyer manuellement des lots de fiches salarié en cas de problème de transmission
    - Traitement des cas non documentés des retours d'intégration ASP

### Modifié

- Fiches salarié :
    - Amélioration de la recherche dans l'admin
    - Amélioration des logs de transfert pour éviter certaines remontées Sentry inutiles
    - Correctif d'un bug du formatage des voies et des extensions (bis, ter…) des adresses suite à un changement dans l'API de géolocalisation (`API Geo`)
    - Correctif pour les données de tests (`fixtures`) de l'environnement de développement
    - Correctif pour les codes des départements d'outre-mer
    - Correctif d'un bug d'absence d'affichage pour les fiches non complétées
    - Correctif d'un bug dans le parcours de saisie de la partie Pôle emploi (*erreur 500*)
    - Correctif d'un bug dans la récupération de données ASP quand une erreur de traitement entraîne le blocage du traitement des fiches restantes dans un lot
- Correctif pour 1659 candidatures sans émetteurs qui empêchaient les entreprises de les accepter ou de les refuser (*erreur 500*)
- Résolution d'une erreur dans le script quotidien *Metabase* provoqué par une grosse requête générant une erreur de mémoire partagée
- Nouveaux tableaux de bord Metabase pour les conseils départementaux et les directions départementales de l'emploi, du travail et des solidarités (*DDETS*)
- Meilleure explication du mécanisme pour envoyer une candidature spontanée : "*Ne rien cocher pour une candidature spontanée*" à la place de "*Optionnel*"
- Meilleure explication des résultats de recherche : "*Les résultats de recherche affichent en priorité les entreprises qui ont reçu peu de candidatures par rapport aux métiers proposés*"
- Correctifs dans le mécanisme d'import des agréments Pôle emploi à cause des incohérences dans le format des données reçues (différents formats de date notamment)
- Mise à jour vers Django 3.2.8
- Mise à jour du SDK Sentry 1.4.3

## [27] - 2021-09-24

### Ajouté

- Ajout d'une étape de confirmation au processus de candidature afin d'éviter qu'une adresse e-mail soit utilisée par différents candidats.
- Ajout d'une étape supplémentaire à la fin du parcours de candidature pour permettre aux prescripteurs de revenir à leur recherche ou d'aller au tableau de bord.
- Ajout du motif de prolongation "CDI conclu avec une personne âgée d'au moins 57 ans (12 mois max)"
- Création et exécution d'un script de fusion des doublons de candidats.
- Brique technique de gestion de France Connect, en vue de faciliter l'identification candidat.
- Ajout d'une page de destination pour présenter l'API.
- Ajout du motif de refus de candidature "Candidat non mobile".
- Ajout d'un champ « Précisez » si le motif du refus sélectionné est « Autre ».

### Modifié

- Mise à jour des motifs et de la durée maximum de suspension.
- Ajout du SIRET dans le message d'avertissement lorsqu'une structure n'est plus conventionnée.
- Remplacement de l'image du logo dans les meta tags par une image au format 1200x630 pixels.
- Ajout le nom de la SIAE dans l'e-mail de confirmation d'envoi transmis au prescripteur.
- Correction des erreurs d'envois d'e-mail en réduisant la longueur du sujet lorsque le nom de la structure est trop long.
- Ajout de la possibilité d'ordonner les différents résultats de l'API SIAE.
- Correctifs sur l'import EA.
- Correctifs mineurs concernant l'envoi des données des fiches salarié.
- Mise en production et ouverture progressive des fiches salarié.

### Supprimé

- Suppression de la mention obsolète sur les motifs de suspension sur le formulaire de suspension.
- Suppression de la mention "(socle)" du critère d'éligibilité "Bénéficiaire du RSA".

## [26] - 2021-09-09

### Ajouté
- Automatisation des imports de données de l'ASP.
- Refonte et réorganisation de la documentation technique.
- Integration du nouveau `datepicker` au thème.
- Ajout d'une option de suppression du suivi Matomo (opt-in / `tarteaucitron`).
- Ajout d'évènements Matomo sur les liens de la page de résultats employeurs.
- Ajout d’une API `/api/v1/siaes` (et sa documentation) pour obtenir la liste des SIAE à proximité d’une ville.

### Modifié
- Correction des erreurs Sentry relatives au format de dates (`datepicker`).
- Correction du message de notification lors d'une demande d'invitation.
- Correction de l'affichage du type de prescripteur.
- Modification d'un message d'erreur lors d'une prolongation de PASS IAE.
- Modification du bouton de déconnexion.
- Mise à jour de l'accès aux statistiques des conseils départementaux.
- Mise à jour des scripts de formatage et de vérification du code.
- Mise à jour des critères d'éligibilité.
- Mise à jour de la liste des prescripteurs habilités.
- Mise à jour vers Django v3.2.7

## [25] - 2021-08-26

### Ajouté
- Ajout d'un bouton pour demander à rejoindre la structure lors de l'inscription d'un prescripteur.
- Ajout de l'information de l'entreprise siège.
- Ajout des dates du PASS IAE dans les fiches salarié.
- Ajout d'une fonctionnalité au processus périodique de transfert des fiches salarié qui permettra d'effacer les données après 13 mois.

### Modifié
- Remplacement technique du composant permettant de saisir des dates afin de permettre la saisie à la main ou par l'intermédiaire d'un calendrier.
- Factorisation technique du code des organisations, des structures et des institutions.
- Résolution d'un bug du formulaire que le candidat utilise pour postuler.
- Simplification du message d'information qui apparaît lors de l'acceptation d'une candidature.
- Résolution d'un bug dans le module de reprise d'agrément s'il a déjà été repris par un autre employeur avant.
- Résolution d'une erreur 500 à la délivrance d'un PASS IAE si la candidature a été acceptée plus d'une fois.
- Résolution d'une erreur 500 à l'import d'un agrément PE si le candidat a déjà un PASS IAE mais n'a aucune candidature acceptée.
- Les tests unitaires fonctionnent maintenant même entre minuit et 2h du matin sur les candidatures.
- Les champs concernant l'adresse d'un candidat deviennent obligatoires dans le tunnel de candidature (avec ajout d'astérisques).
- Dans les menus de sélection du département, la liste commence désormais par leur numéro afin de pouvoir utiliser le clavier pour aller plus vite.
- Correction de la balise META du logo dans l'en-tête HTML pour utiliser le nouveau logo.
- Préparation de l'ouverture progressive de la fonctionnalité des fiches salarié.

## [24] - 2021-08-12

### Ajouté
- Affichage d'un message informatif sur la page de détails d'une candidature si le diagnostic d'éligibilité est expiré.
- Écran d'auto-prescription des employeurs : ajout du nom du candidat dans le titre.
- Le _push_ sur une branche qui a l'étiquette « recette-jetable » déclenche un nouveau déploiement.
- Page de statistiques : ajout d'un lien vers le pilotage de l'inclusion.

### Modifié
- Menu supérieur droit des employeurs : l'étiquette du type de structure est désormais à gauche.
- Un candidat qui a un diagnostic valide peut désormais postuler par lui-même.

### Supprimé
- Motif de prolongation suivant : la personne rencontre des difficultés faisant obstacle à son insertion professionnelle.

## [23] - 2021-07-29

### Ajouté

- Nouveau workflow vers « Obtenir un PASS IAE » lorsque l'agrément à prolonger ou suspendre
  est utilisé par une autre structure
- Ajout d'un message d'aide et d'un lien vers le support en cas d'erreur 500
- Le prescripteur doit saisir le SIREN et le département de son organisation
  lors de l'inscription pour qu'il puisse vérifier qu'un création est nécessaire
  afin de réduire les doublons.
- Mise en forme du SIRET (ex. 123 456 789 00001)
- Nouvelle application pour les institutions
- Nouvelle variables Matomo pour les inspecteurs du travail
- Les utilisateurs VIP peuvent consulter les statistiques des Conseils Départementaux

### Modifié

- Recherche du dernier PASS IAE lors de la recherche via le numéro d'agrément
- Affichage du type de la structure au moment de la candidature pour éviter les confusions
  car de nombreuses structures portent le même nom
- Renommage du critère « Jeunes (-26 ans) » au singulier
- Message d'aide pour le indiquer le format du numéro d'agrément attendu
- Nouvelle organisation des tests sur les agréments et réduction du temps de traitement de 10 %
- Utilisation du champ de type e-mail pour faciliter la saisie sur mobile (et la vérification côté
  client).
- Affichage du résultat de recherche envoyé à l'API Sirene en cas d'erreur
- Le champ de SIRET devient un libellé avec les 9 premiers chiffres et 5 chiffres déterminant
  l'établissement en saisie pour réutiliser le SIREN de la première étape
- Ajout de contrôles lors du tunnel d'inscription
- Modification du traitement des données à l'utilisation de l'API Sirene
- L'instance de démo utilise un addon PostgreSQL dédié
- Transfert des ressources utilisées par les recettes jetables dans une
  organisation Clever Cloud dédiée
- Possibilité d'accepter une candidature précédemment annulée
- Changement du libellé « Continuer avec un CV » par « Continuer »
- DDEETS devient DDETS
- L'affichage de l'icône « Marque-page » est seulement affiché si nécessaire
  dans le Tableau de bord

## [22] - 2021-07-15

### Ajouté

- Affichage du lien d'invitation sur la page de gestion des collaborateurs
- Affichage du prénom et du nom de la personne invitée dans le titre de la page cible de l'invitation
- API d'accès aux fiches salarié
- Création des APIs d'appel Pôle emploi RechercheIndividuCertifie et MiseAJourIAE
- Ajout d'une plateforme expérimentale de suivi des logs (ElasticSearch + Kibana)
- Mise en place des transferts de fichiers automatiques vers l'ASP (fiches salarié)

### Modifié

- Filtrage des agréments Pôle emploi qui démarrent dans le futur afin qu'ils n'apparaissent pas dans les résultats d'import
- Traduction en français du message d'erreur produit lorsque le mot de passe est similaire à l'adresse e-mail
- Harmonisation de l'affichage des messages d'erreurs de formulaire
- Correction d'un bug lors du téléchargement d'un PASS IAE lorsque ce dernier n'est lié à aucun diagnostic
- Correction sur les invitations, un membre retiré d'une structure peut désormais être réinvité
- Correction des erreurs 404 sur la reprise d'un agrément Pôle emploi lorsque la SIAE destinataire de la dernière candidature n'est pas la SIAE connectée
- Mise à jour du SDK sentry de la version 1.1.0 vers 1.3.0

## [21] - 2021-07-02

### Ajouté

 - Configuration de Sentry pour remonter les warnings
 - Rendre possible la suspension d'une candidature sans date de début
 - Admin: filtrer les candidatures crées à partir d’un agrément pole emploi
 - Ajout d'un accès sécurisé pour les CD aux stats de leur département
 - Export régulier pour les comités technique d'animation (C.T.A.)
 - Nouvelle page "Déclaration d'accessibilité"
 - Message de demande d’activation de JavaScript sur le formulaire d’upload de CV
 - Test de caracterisation pour le comportement d’un agrément PE dont la date est dans le futur, et où on accepte la candidature maintenant
 - Ajout d’une commande 'make deploy_prod'
 - Ajout d’un script de réimport de base de données
 - Génération d'un CSV à partir d'un script SQL

### Modifié

 - Mise à jour vers Django 3.2.5
 - Écrans fiches salarié
 - Tri des résultats de recherche employeur par score (et non plus de manière aléatoire)
 - Les demandeurs d'emploi ne doivent pas pouvoir changer leur adresse mail dans la modification de leur profil
 - Correctif pour pouvoir modifier une prolongation dans l'admin
 - Respect des réactivations de convention par le support pendant 90 jours au lieu d'une semaine
 - Relier les diagnostics d'éligibilité aux candidatures
 - Corrections de typos (PASS IAE) et renommages divers:
   - Renommage "SIAE" devient "Entreprise" dans l’administration
   - Renommage "Agrément" devient "Pass IAE" dans l’administration
   - Correction de l’étiquette "adresse email" lors de la création du candidat dans une candidature

### Supprimé

 - Désactivation des conventions sans AF 2021
 - Simplification du code lié aux diagnostics
 - Suppression des paramètres des `review apps` (au profit d’un Github Secret)

## [20] - 2021-06-17

### Ajouté
- Un formulaire de situation avant l'inscription d'un demandeur d'emploi
- Table de liaison entre la table « Fiches de poste » et la table « Candidatures »
- 4 nouvelles tables ASP dans Metabase
- Message informatif sur la page de désactivation d'un membre
- Commande pour générer le thème avec `git subtree`
- Les employeurs voient la raison du refus d'un PASS IAE
- Le formulaire d'ajout d'un CV s'affiche seulement si Javascript est activé
- Automatisation d’une sauvegarde régulière de la base de données sur un autre serveur que celui de production
- Possibilité d'importer un agrément Pôle Emploi afin de le prolonger ou le suspendre depuis la plateforme

### Modifié
- Les prescripteurs doivent confirmer les prolongations en transférant un e-mail au support
- Remplacement de la fenêtre surgissante « Obtention d'un PASS IAE » par des boutons en bas du formulaire
- Mise à jour des coordonnées géographiques d'Arles
- Les prescripteurs peuvent de nouveau voir le motif et le message de refus des candidatures envoyées
- Traitement des structures créées par le support (fin de l'immunité)
- Renommage du script metabase `populate_metabase` en `populate_metabase_itou`
- Simplification du script d'import des SIAE (abandon du _dry run_)
- Mise à jour du bandeau de consentement aux cookies
- Seuls les administrateurs peuvent modifier la fiche publique de leur établissement
- Ajout et modification des réseaux sociaux
- Refonte du moteur de recherche employeurs et prescripteurs (avec ajout de filtres)

### Supprimé
- Bouton « Tarte au citron » quand les cookies ont été acceptés
- Suppression de l'adresse contact@ des notifications courriel concernant les PASS IAE

## [19] - 2021-06-04

### Ajouté

- Possibilité d'afficher le détail d'une candidature pour les prescripteurs
- Test pour s'assurer de la couverture une branche du code de la délivrance manuelle d'un PASS IAE (dans la vue `accept`)
- Possibilité pour un employeur de supprimer une candidature de son tableau de bord
- Case à cocher pour indiquer si l'organisme est conventionné par le conseil départemental pour le suivi des BRSA, cette information est désormais indépendante de la catégorie de l'organisation (avec nettoyage de la base)
- Texte pour bien faire comprendre aux employeurs que la date de début d'embauche a une incidence sur le début du parcours et le versement de l'aide au poste
- Texte pour ajouter un avertissement sur la conservation des pièces justificatives en cas de contrôle a posteriori
- Si un ID PE est renseigné, alors il prend la priorité sur le champ permettant de préciser le motif de son absence afin d'éviter un message d'erreur difficile à comprendre pour les utilisateurs
- Ajout d'un lien vers la documentation sur la période de carence
- Ajout d'un contrôle de sécurité des données envoyées dans l'interface de configuration des fiches de poste

### Modifié

- Seul le créateur d'un compte candidat peut en modifier l'e-mail
- Les candidatures refusées peuvent être acceptées
- Nouveau système pour joindre un CV à une candidature
- Prise en compte de l'extension COVID pour les agréments pré-existants dans le contrôle sur la date de fin d'embauche qui ne doit pas dépasser le temps restant d'un parcours IAE
- Correctif pour l'erreur "Cette ville n'existe pas" avec ajout de tests unitaires sur `AddressFormMixin`
- Les enquêtes de satisfaction SIAE et prescripteurs contiennent plus de données qualifiées sur les répondants
- Deux emails distincts sont envoyés lors de l'acceptation d'une candidature, un pour le candidat et un pour son orienteur/prescripteur le cas échéant (auparavant l'orienteur/prescripteur était en copie cachée)
- Utilisation d'une constante dans les *settings* pour le lien vers Typeform
- Désactivation d'un log afin d'éviter d'atteindre les limites du quota Sentry
- Correctif pour une valeur manquante dans la configuration qui empêchait d'embaucher avec délivrance manuelle de nouveau PASS IAE (a concerné seulement 2 utilisateurs)
- Un orienteur peut maintenant candidater vers une EA ou un GEIQ même si son candidat a un parcours IAE dans le délai de carence
- Renommage de l'URL du "Journal des modifications" en /versions/`
- Affichage des mois au format texte long sur l'écran d'export des candidatures
- Dans la liste des candidatures, le nom de l'employeur devient un lien vers sa fiche publique pour accéder aux coordonnées facilement
- Amélioration technique de la commande de fusion des organisations de prescripteurs (uniquement accessible par les devs)
- Correctif pour les ACIPHC créées par le support pour corriger l'import SIAE
- Mise à jour vers le SDK Sentry 1.1.0
- Mise à jour vers Django 3.2.4 (correctifs)

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

- Ajout de l'interface "Mes annexes financières"
- Ajout d'un formulaire pour connaitre le secteur d'activité des employeurs
- Ajout d'une redirection de `inclusion.beta.gouv.fr/dashboard` vers `emplois.inclusion.beta.gouv.fr/dashboard` pour ne pas induire en erreur les usagers suite au changement de nom de domaine.
- Ajout de la colonne "date de création" pour permettre au support de voir les structures créés lors des imports.

### Modifié

- Nouvelle version majeure de Django v3.2
- Changement du code de tracking Hotjar
- Amélioration des performances de l'enregistrement de la session utilisateur
- Correction du bug qui empeche la prolongation d'une ACI pour "difficultés particulières"
- Possibilité de modifier l'email d'un demandeur tant que celui ci n'a pas confirmé son compte
- Simplification des invitations:
  - Les invitations ne partent plus en plusieurs exemplaires quand l'utilisateur clique à répétition sur le bouton d'envoi
  - Si une invitation est renouvelée pour un utilisateur, il n'y a plus de nouvelle invitation créée en base (moins d'entrées dans le tableau de bord)
  - Environ 4500 invitations en doublon ont été supprimées de la base de données
- Correction de l'affichage des emails où des éléments sur les structures manquaient.
- Amélioration de l'affichage des critères d'éligibilité pour les candidatures envoyées par des prescripteurs habilités
- Utilisation d'une compte dédié pour les emails de la plateforme, afin de réduire le risque de classification en spam des emails applicatifs.

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
- Le bouton "Télécharger l'attestation" devient "Télécharger le PASS IAE"
- Le statut de candidature "Embauche pour plus tard" a été remplacé par "Candidature en liste d'attente"

### Supprimé

- Pour les GEIQ et les EA, retrait de la note informative "PASS IAE et demande rétroactive"

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
- Ajout d'un lien vers le décret concernant les critères d'éligibilité
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
