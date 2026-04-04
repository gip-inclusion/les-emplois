# Tableaux de Bord & Reporting


### 10.1 Tableau de Bord Employeur

**Sections Clés :**

1. **Vue Ensemble Candidatures en Attente :**
   - Compte candidatures dans états NEW, PROCESSING, POSTPONED
   - Groupé par état
   - Accès rapide listes candidatures

2. **Candidatures Récentes :**
   - 20 dernières candidatures reçues
   - Avec date dernier changement (créée ou dernière transition)
   - Filtre par état

3. **Gestion Équipe :**
   - Liste membres actifs
   - Inviter nouveaux membres
   - Gérer droits admin

4. **Informations Entreprise :**
   - Mettre à jour détails entreprise
   - Gérer descriptions poste
   - Statut annexe financière

5. **Fiches Salarié :**
   - Liste fiches salarié par statut
   - Liens rapides créer/mettre à jour
   - Statut traitement ASP

**Métriques Affichées :**
- Total candidatures (tous temps)
- Candidatures ce mois
- Embauches ce mois
- Descriptions poste actives

### 10.2 Tableau de Bord Prescripteur

**Sections Clés :**

1. **Gestion Demandeurs Emploi :**
   - Liste demandeurs emploi créés
   - Liste demandeurs emploi pour qui candidatures soumises
   - Filtre par statut éligibilité

2. **Suivi Candidatures :**
   - Candidatures envoyées
   - Candidatures en attente
   - Candidatures acceptées

3. **Gestion Organisation :**
   - Membres
   - Statut habilitation
   - Statut convention BRSA

4. **Candidats Bloqués :**
   - Demandeurs emploi sans progrès récent
   - Filtre par statut bloqué
   - De tous collègues ou juste utilisateur

**Métriques :**
- Demandeurs emploi suivis
- Candidatures soumises
- Embauches facilitées

### 10.3 Tableau de Bord Demandeur Emploi

**Sections Clés :**

1. **Historique Candidatures :**
   - Toutes candidatures avec statut
   - Filtre par état
   - Détails candidature

2. **Agrément Actif :**
   - PASS IAE actuel
   - Période validité
   - Suspensions
   - Prolongations

3. **Gestion Profil :**
   - Informations personnelles
   - Situation administrative
   - Télécharger CV

4. **Rendez-vous Prochains :**
   - Rendez-vous RDV-Insertion
   - Statut participation

### 10.4 Statistiques & Analytics

#### Statistiques Plateforme

**Métriques Disponibles :**

1. **Statistiques Candidatures :**
   - Comptes candidatures mensuelles
   - Taux acceptation
   - Temps moyen décision

2. **Statistiques Embauches :**
   - Embauches mensuelles par région
   - Par type entreprise
   - Par type prescripteur

3. **Statistiques Agréments :**
   - PASS IAE délivrés (mensuel)
   - Prolongations accordées
   - Suspensions créées

4. **Statistiques Utilisateurs :**
   - Utilisateurs actifs par type
   - Nouvelles inscriptions
   - Distribution géographique

**Patterns Requête :**
```python
# Comptes mensuels
job_applications = JobApplication.objects.with_monthly_counts()
# Retourne : [{month: date, c: count}, ...]

# Agrégation géographique
by_department = Company.objects.values('department').annotate(count=Count('pk'))
```

#### Intégration Matomo

**Événements Analytics Suivis :**
- Vues pages
- Actions utilisateur (postuler, accepter, refuser)
- Tunnels conversion
- Requêtes recherche

**Suivi Type Compte :**
```python
MATOMO_ACCOUNT_TYPE = {
    UserKind.PRESCRIBER: "prescripteur",
    UserKind.EMPLOYER: "employeur inclusif",
}
```

#### Tableaux Bord Metabase

**Tableaux Bord Intégrés :**
- Tableau bord performance employeur
- Tableau bord activité prescripteur
- Tableau bord statistiques régionales
- Tableau bord KPI national

**Contrôle Accès :**
- Filtres spécifiques utilisateur
- Accès basé rôle
- Permissions téléchargement


