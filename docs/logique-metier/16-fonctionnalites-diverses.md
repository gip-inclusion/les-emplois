# Fonctionnalités Additionnelles


### 16.1 Parcours Bienvenue

**Objectif :** Intégrer nouveaux utilisateurs avec visite guidée

**Implémentation :**
- Indicateur booléen `has_completed_welcoming_tour`
- Visite interactive étape par étape
- Visites spécifiques rôle (employeur, prescripteur, demandeur emploi)
- Suivi achèvement

### 16.2 Invitations

**Modèle Invitation :**
- Invitations par email aux organisations
- Dates expiration
- Suivre statut envoyé/accepté/expiré

**Types Invitations :**
1. Invitations adhésion entreprise
2. Invitations organisation prescripteur

**Demande Invitation :**
- Utilisateurs peuvent demander rejoindre organisations
- Admins organisation approuvent/refusent

### 16.3 Annonces

**Modèle AnnouncementCampaign :**
- Annonces plateforme
- Bannières rejetables
- Suivi campagne active

**Cas d'Usage :**
- Lancements fonctionnalités
- Fenêtres maintenance
- Mises à jour importantes

### 16.4 Notes Version

**Objectif :** Informer utilisateurs changements plateforme

**Affichage :**
- Numéros version
- Descriptions fonctionnalités
- Points forts améliorations

### 16.5 Tâches Fond (Huey)

**Types Tâches :**

1. **Envoi Email :**
   - Livraison asynchrone
   - Nouvelle tentative échec

2. **Notifications Pôle Emploi :**
   - Notifications agrément
   - Logique nouvelle tentative

3. **Traitement Fiche Salarié :**
   - Génération lot ASP
   - Traitement retour

4. **Import Données :**
   - Imports gros ensembles données
   - Sync données ASP/GEIQ

5. **Tâches Planifiées (Cron) :**
   - Quotidien : Détection candidat bloqué
   - Quotidien : Archivage fiche salarié
   - Quotidien : Nouvelle tentative notification agrément
   - Hebdomadaire : Vérifications qualité données

**Configuration :**
- Backend Redis pour file tâches
- Processus consommateur Huey
- Surveillance et journalisation tâches

### 16.6 Données Géographiques

**Villes & Départements :**

**Modèle City :**
- `name` : Nom ville
- `slug` : Slug compatible URL
- `post_codes` : Tableau codes postaux
- `department` : FK vers Department
- `coords` : Point géocodé
- `population` : Pour tri

**Modèle Department :**
- `code` : Code 2-3 chiffres
- `name` : Nom département
- `region` : FK vers Region
- `timezone` : Fuseau horaire (principalement Europe/Paris)

**Calculs Distance :**
Fonctions PostGIS pour requêtes géographiques :
```python
companies = Company.objects.within(point, distance_km=25)
```


