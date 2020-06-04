# Journal des modifications (*Changelog*)

Toutes les modifications notables apportées au projet seront documentées dans ce fichier.

Le format est basé sur [Tenez un Changelog](https://keepachangelog.com/en/1.0.0/), et ce projet adhère au [*Semantic Versioning*](https://semver.org/spec/v2.0.0.html).

## [1.0.4] - 2020-06-04

### Ajouté
- Indicateur de validation de l'email dans l'admin (partie utilisateur)
- Envoi d'un email au support lors du rattachement d'un prescripteur à une structure sans membres
- Inscription sans boite email (redirection vers PE connect) 
- Connexion via PE Connect
- Tracking Matomo pour PE Connect
- Liens Typeform lors de l'envoi d'email (confirmation d'embauche pour les SIAE et prescripteurs) 
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
