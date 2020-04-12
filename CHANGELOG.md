# Journal des modifications (*Changelog*)

Toutes les modifications notables apportées au projet seront documentées dans ce fichier.

Le format est basé sur [Tenez un Changelog](https://keepachangelog.com/en/1.0.0/), et ce projet adhère au [*Semantic Versioning*](https://semver.org/spec/v2.0.0.html).

## [Non publié]
- Nouveau mécanisme d'inscription orienteur/prescripteur
- Possibilité d'annuler un agrément
- Possibilité de se connecter avec PE Connect

## [0.0.1] - 2020-04-13

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
