# Intégrations & APIs Externes


### 9.1 API France Travail (Pôle emploi)

#### Intégration API Partenaire

**Points Terminaison Utilisés :**

1. **Recherche Individu Certifié**
   - Objectif : Certifier identité demandeur emploi et obtenir NIR obfusqué
   - Entrée : first_name, last_name, nir, birthdate
   - Sortie : `id_national_pe` (identifiant obfusqué)
   - Stocké dans : `jobseeker_profile.pe_obfuscated_nir`
   - Crée : Enregistrement `IdentityCertification`

2. **Mise à Jour PASS IAE**
   - Objectif : Notifier France Travail création/mise à jour agrément
   - Entrée : Données agrément, ID certifié demandeur emploi, infos SIAE
   - Sortie : Code succès/erreur
   - Met à jour : `approval.pe_notification_status`

**Gestion Erreurs :**

**Codes Sortie (Recherche Individu) :**
- `PE001` : Individu trouvé et certifié
- `PE004` : Individu pas trouvé
- `PE008` : Individus multiples trouvés (ambigu)
- Autres : Erreurs diverses

**Codes Sortie (Mise à Jour PASS IAE) :**
- Codes succès : Agrément mis à jour
- Codes erreur : Erreurs validation, doublon, etc.

**Stratégie Nouvelle Tentative :**
- Erreurs récupérables (réseau, timeout) : Nouvelle tentative
- Erreurs irrécupérables (données invalides) : Pas nouvelle tentative, journaliser comme ERROR
- Transitions statut notification :
  - PENDING → SHOULD_RETRY (erreur temporaire)
  - PENDING → ERROR (erreur permanente)
  - PENDING → SUCCESS (réussi)

#### Tâches Cron Notification

**Premier Passage :** Traiter agréments avec statut SHOULD_RETRY
**Second Passage :** Traiter agréments avec statut PENDING

**Vérifications Préliminaires :**
Avant notifier, vérifier :
- Agrément ne commence pas dans futur
- Utilisateur a données requises (nom, NIR, date naissance)
- Type SIAE valide
- Candidature acceptation existe

### 9.2 Intégration API Particulier

**Objectif :** Certifier identité demandeur emploi via API gouvernement

**Processus Certification :**
1. Utilisateur donne consentement
2. Appel API avec NIR, date naissance
3. API retourne données certifiées
4. Champs verrouillés en lecture seule

**Champs Certifiés :**
- User : first_name, last_name, birthdate
- Profile : nir, birth_place, birth_country

**Application Lecture Seule :**
Après certification, champs ne peuvent être édités (appliqué dans formulaires) :
```python
def readonly_pii_fields(self):
    blocked_fields = set()
    for certification in self.identity_certifications.all():
        if certification.certifier == IdentityCertificationAuthorities.API_PARTICULIER:
            blocked_fields.update(api_particulier.USER_REQUIRED_FIELDS)
            blocked_fields.update(api_particulier.JOBSEEKER_PROFILE_REQUIRED_FIELDS)
    return blocked_fields
```

### 9.3 APIs Adresse & Géocodage

#### BAN (Base Adresse Nationale)

**Objectif :** Valider et géocoder adresses françaises

**Utilisation :**
- Autocomplétion adresse
- Récupération coordonnées
- Extraction code INSEE

**Intégration :**
```python
from itou.common_apps.address import geocoding

result = geocoding.get_geocoding_data(address, post_code=None)
# Retourne : {
#     'address': formatted_address,
#     'latitude': lat,
#     'longitude': lon,
#     'score': confidence_score,
#     'city': city_name,
#     'post_code': post_code,
# }
```

#### API Geo

**Objectif :** Données commune INSEE et département

**Utilisation :**
- Extraction département depuis code postal
- Recherche commune par code INSEE

### 9.4 API SIRET INSEE

**Objectif :** Valider numéros SIRET/SIREN entreprises

**Utilisation :**
- Validation enregistrement entreprise
- Récupération informations légales
- Validation code NAF

**Intégration :**
Configuré dans paramètres, utilisé durant création/mise à jour entreprise.

### 9.5 API Data Inclusion

**Objectif :** Découvrir structures inclusion externes

**Intégration :**
Recherche structures par :
- Localisation
- Score qualité
- Type source

Retourne structures pas dans base données plateforme.

### 9.6 Intégration RDV-Insertion

**Objectif :** Planifier rendez-vous avec demandeurs emploi

**Modèles :**

1. **Participation :**
   - `job_seeker` : FK vers utilisateur
   - `appointment__company` : FK vers entreprise
   - `appointment__start_at` : Datetime rendez-vous
   - `status` : UNKNOWN, SEEN, ABSENT, CANCELLED

2. **Invitation :**
   - Créée quand employeur invite demandeur emploi
   - Trace statut invitation

**Gestion Webhook :**
RDV-Insertion envoie webhooks sur :
- Rendez-vous créé
- Rendez-vous mis à jour
- Statut participation changé

**Affichage :**
Rendez-vous prochains affichés dans liste candidatures :
```python
.with_next_appointment_start_at()
.with_upcoming_participations_count()
```

### 9.7 Intégration Diagoriente

**Objectif :** Évaluation compétences demandeurs emploi

**Intégration :**
- Envoyer lien invitation
- Suivre statut invitation
- Pas intégration temps réel

### 9.8 Intégration Formulaires Tally

**Objectif :** Enquêtes satisfaction

**Intégration :**
- Enquêtes post-embauche (employeur, demandeur emploi)
- Enquêtes satisfaction prescripteur
- Génération URL avec contexte pré-rempli

**Exemple :**
```python
survey_url = get_tally_form_url(
    "mY59xq",  # ID formulaire
    id_siae=company.pk,
    type_siae=company.get_kind_display(),
    region=company.region,
    departement=company.department,
)
```

### 9.9 Intégration Metabase

**Objectif :** Tableaux bord analytiques avancés

**Fonctionnalités :**
- Tableaux bord intégrés avec JWT signé
- Tableaux bord spécifiques utilisateur
- Capacité téléchargement (CSV, XLSX, JSON, PNG)
- Contrôle accès via permissions


