# Gestion des Organisations


### 2.1 Gestion des SIAE (Entreprises)

#### Types d'Entreprises (CompanyKind)
9 types de structures d'emploi inclusif :

1. **EI** - Entreprise d'insertion
2. **AI** - Association intermédiaire
3. **ACI** - Atelier chantier d'insertion
4. **ETTI** - Entreprise de travail temporaire d'insertion
5. **EITI** - Entreprise d'insertion par le travail indépendant
6. **GEIQ** - Groupement d'employeurs pour l'insertion et la qualification
7. **EA** - Entreprise adaptée
8. **EATT** - Entreprise adaptée de travail temporaire
9. **OPCS** - Organisation porteuse de la clause sociale

#### Catégories de SIAE

**SIAE Soumises aux Règles IAE** (nécessitent conventions et PASS IAE) :
- EI, AI, ACI, ETTI, EITI

**SIAE Soumises aux Règles d'Éligibilité** (nécessitent diagnostic d'éligibilité) :
- Toutes les SIAE IAE + GEIQ

**Entreprises avec Fiches Salarié ASP** :
- ACI, AI, EI, EITI, ETTI

#### Champs Principaux Entreprise

**Identification :**
- `siret` : SIRET 14 chiffres (unique par kind) - identifiant principal
- `naf` : Code NAF (activité)
- `kind` : Type d'entreprise (requis)
- `name` : Nom légal
- `brand` : Nom commercial (remplace name si défini)
- `source` : Source de données (ASP, GEIQ, EA_EATT, USER_CREATED, STAFF_CREATED)

**Informations de Contact :**
- `phone`, `email` : Contact public
- `auth_email` : Email d'authentification inscription sécurisée (depuis imports externes)
- `website`, `description`, `provided_support` : Infos marketing

**Localisation** (via AddressMixin) :
- Champs adresse + coordonnées géocodées
- `department`, `region` : Dérivés du code postal
- `coords` : Champ Point pour requêtes géographiques

**Contrôle d'Activité :**
- `block_job_applications` : Interrupteur principal pour toutes les candidatures
- `job_applications_blocked_at` : Horodatage dernier blocage
- `spontaneous_applications_open_since` : NULL = fermé, horodatage = ouvert (périodes 90 jours)

### 2.2 Logique d'Activation Entreprise

#### Définition Entreprise Active
Une entreprise est considérée "active" selon des règles complexes :

```python
# Fichier : itou/companies/models.py:36-57
@property
def active_lookup(self):
    # GEIQ, EA, EATT, OPCS : Toujours actives (pas besoin de convention)
    ~Q(kind__in=CompanyKind.siae_kinds())

    # STAFF_CREATED : Toujours active (temporaire jusqu'import ASP)
    | Q(source=Company.SOURCE_STAFF_CREATED)

    # ASP/USER_CREATED SIAE : Active seulement si a convention active
    | has_active_convention
```

**Logique de Période de Grâce :**
Les SIAE inactives obtiennent une période de grâce de 30 jours après désactivation convention :
- `grace_period_end_date` : deactivated_at + 30 jours
- Pendant période grâce : les membres peuvent toujours accéder à leurs données
- Après période grâce : accès restreint

#### Recherche & Découverte Entreprises
Les entreprises peuvent être trouvées via :
- Recherche géographique (dans rayon depuis coordonnées)
- Filtrage par catégorie métier
- Filtrage statut actif
- Statut embauche (a postes actifs ou accepte candidatures spontanées)

**Score de Candidature Calculé :**
Assure distribution équitable des candidatures entre employeurs :
```
score = (nombre_candidatures_récentes) / max(nombre_postes_ouverts, 1)
```
- Score plus bas = boosté dans résultats recherche
- Postes ouverts = descriptions poste actives + (1 si candidatures spontanées ouvertes sinon 0)
- Score par défaut nouvelles entreprises : sys.float_info.max (envoyées dernière page)

### 2.3 Conventions Financières & Annexes

#### Modèle SiaeConvention
Contrat légal requis pour SIAE pour opérer :

**États :**
- `is_active` : Booléen indiquant si convention actuellement valide
- `deactivated_at` : Horodatage désactivation convention
- GRACE_PERIOD = 30 jours après désactivation

**Champs Convention :**
- `siret_signature` : SIRET à la signature convention (change presque jamais)
- `asp_id` : Identifiant unique ASP pour la convention
- Plusieurs SIAE peuvent partager même convention (via FK)

#### Modèle SiaeFinancialAnnex
Annexes financières (AF) attachées aux conventions :

**États AF** (Statut AF) :
- `VALIDE` : Valide et active
- `PROVISOIRE` : Provisoire/temporaire
- `HISTORISE` : Archivée/historique
- `ANNULE` : Annulée
- `SAISI` : En cours de saisie
- `BROUILLON` : Brouillon
- `CLOTURE` : Clôturée
- `REJETE` : Rejetée

**Champs AF :**
- `number` : Numéro AF (format : AFXXXXX)
- `state` : État actuel (ci-dessus)
- `start_at`, `end_at` : Période de validité
- `convention` : FK vers convention parente

**Règles Métier :**
- Les fiches salarié doivent être liées à une annexe financière valide
- Quand AF désactivée, période de grâce s'applique aux SIAE attachées
- Réactivation manuelle possible par le staff

### 2.4 Organisations de Prescripteurs

#### Types d'Organisations
Les prescripteurs peuvent appartenir à divers types d'organisations :

**Prescripteurs Habilités** (peuvent créer diagnostic d'éligibilité) :
- Pôle emploi (France Travail)
- Mission locale
- Cap emploi
- Départements
- CCAS/CIAS
- Et autres...

**Champs Organisation :**
- `kind` : Type d'organisation (100+ choix)
- `authorization_status` : VALIDATED, REFUSED, PENDING, NOT_SET
- `code_safir_pole_emploi` : Code SAFIR pour agences France Travail
- `has_brsa_convention` : Convention pour bénéficiaires RSA

**Logique d'Habilitation :**
```python
is_authorized = authorization_status == PrescriberAuthorizationStatus.VALIDATED
```

**Les prescripteurs habilités peuvent :**
- Créer des diagnostics d'éligibilité IAE
- Outrepasser la période de carence pour PASS IAE
- Demander des prolongations PASS IAE

### 2.5 Adhésion Organisation

#### Modèle CompanyMembership
Lie les utilisateurs aux entreprises pour lesquelles ils travaillent :

**Champs :**
- `user` : FK vers utilisateur
- `company` : FK vers entreprise
- `is_admin` : Indicateur droits admin
- `joined_at` : Date début adhésion
- `is_active` : Indicateur adhésion active

**Logique Métier :**
- Les admins peuvent : inviter membres, gérer entreprise, traiter candidatures
- Les membres réguliers peuvent : voir candidatures, participer au recrutement
- `active_or_in_grace_period_company_memberships()` : Retourne entreprises accessibles

#### Modèle PrescriberMembership
Structure similaire pour organisations de prescripteurs :
- `user`, `organization`, `is_admin`, `joined_at`, `is_active`

**Système d'Invitation :**
- Invitations par email avec expiration
- Flux de demande d'invitation
- Invitations en attente suivies


