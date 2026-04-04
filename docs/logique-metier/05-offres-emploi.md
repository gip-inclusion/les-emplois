# Descriptions de Poste & Recrutement


### 5.1 Gestion Descriptions de Poste

#### Modèle JobDescription
Offres d'emploi créées par SIAE pour attirer candidats.

**Champs Principaux :**
- `company` : FK vers SIAE
- `custom_name` : Remplacement titre poste optionnel
- `description` : Texte description poste
- `contract_type` : Type contrat (depuis enum ContractType)
- `location` : Remplacement localisation (ou utilise localisation entreprise)
- `hours_per_week` : Heures travail
- `open_positions` : Nombre postes
- `profile_description` : Profil candidat requis
- `is_resume_mandatory` : Indicateur exigence CV
- `is_qpv_mandatory` : Exigence clause QPV
- `market_context_description` : Contexte marché
- `is_active` : Statut actif/inactif
- `source` : MANUALLY ou HIRING (créé auto à embauche)
- `ui_rank` : Ordre affichage (plus bas = priorité plus haute)

**Types Contrat par Type Entreprise :**

**GEIQ :**
- APPRENTICESHIP, PROFESSIONAL_TRAINING, OTHER

**EA/EATT :**
- PERMANENT, FIXED_TERM, TEMPORARY, FIXED_TERM_TREMPLIN, APPRENTICESHIP, PROFESSIONAL_TRAINING, OTHER

**EITI :**
- BUSINESS_CREATION, OTHER

**OPCS :**
- PERMANENT, FIXED_TERM, APPRENTICESHIP, PROFESSIONAL_TRAINING, OTHER

**ACI/EI/AI/ETTI (SIAE IAE) :**
- FIXED_TERM_I, FIXED_TERM_USAGE, TEMPORARY, PROFESSIONAL_TRAINING, OTHER
- Spécial pour ACI Convergence : FIXED_TERM_I_PHC, FIXED_TERM_I_CVG

**Liaison Appellation :**
Descriptions poste lient aux appellations ROME (codes métier) :
- Relation M2M via champ `jobs`
- Utilise modèle `rome.Appellation`
- Appellations multiples par description poste

#### Suivi Fraîcheur Poste
- `updated_by` : Dernier employeur ayant mis à jour
- Auto-rafraîchissement nécessaire après 60 jours
- Affecte classement dans résultats recherche

### 5.2 Intégration Postes Externes

#### Intégration Source Poste
Plateforme peut importer postes depuis sources externes :

**Sources Supportées :**
1. **Offres PEC Pôle emploi**
   - `source = JobSource.PE_API`
   - `source_tag = JobSourceTag.FT_PEC_OFFER`
   - Lié à entreprise spéciale Pôle emploi

2. **Offres EA Pôle emploi**
   - `source = JobSource.PE_API`
   - `source_tag = JobSourceTag.FT_EA_OFFER`
   - Pour entreprises adaptées

**Champs Poste Externe :**
- `source_id` : ID poste externe
- `source_url` : Lien vers annonce externe
- `contract_nature` : Nature contrat (ex : PEC_OFFER)

**Logique Affichage :**
Postes externes affichés avec descriptions postes internes dans résultats recherche.

### 5.3 Recherche & Découverte Postes

#### Filtres Recherche

**Recherche Géographique :**
- `city` : Autocomplétion nom ville
- `distance_km` : Rayon depuis ville (5, 10, 25, 50, 100 km)
- Utilise requête PostGIS `coords__dwithin`

**Catégorie Métier :**
- `appellation` : Code métier ROME
- Filtre par descriptions postes liées à appellation

**Filtres Entreprise :**
- `is_active` : Entreprises actives uniquement
- `is_hiring` : Entreprises avec postes actifs ou candidatures spontanées ouvertes
- `kind` : Type entreprise (AI, EI, ACI, etc.)

**Champs Calculés pour Classement :**

1. **count_recent_received_job_apps :**
   Candidatures reçues dans les dernières N semaines
   ```python
   WEEKS_BEFORE_CONSIDERED_OLD = 8
   ```

2. **count_active_job_descriptions :**
   Nombre annonces actives

3. **is_hiring :**
   ```python
   is_hiring = (
       not block_job_applications
       and (
           count_active_job_descriptions > 0
           or spontaneous_applications_open_since is not None
       )
   )
   ```

4. **computed_job_app_score :**
   Score distribution équitable (voir section 2.1)

**Ordre Résultats :**
```python
# Primaire : Score candidature (croissant - score plus bas en premier)
# Secondaire : Distance depuis point recherche (croissant)
# Tertiaire : Nom (alphabétique)
order_by('computed_job_app_score', 'distance', 'name')
```


