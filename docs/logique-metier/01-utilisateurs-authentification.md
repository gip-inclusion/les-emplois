# Gestion des Utilisateurs & Authentification


### 1.1 Système Multi-Rôles

#### Types d'Utilisateurs (UserKind)
La plateforme supporte 5 types d'utilisateurs distincts, chacun avec des permissions et capacités spécifiques :

1. **Demandeurs d'emploi (`JOB_SEEKER`)** - Personnes cherchant un emploi dans les structures inclusives
2. **Employeurs (`EMPLOYER`)** - Membres d'entreprises gérant le recrutement dans les structures SIAE
3. **Prescripteurs (`PRESCRIBER`)** - Conseillers (habilités ou non) orientant les demandeurs d'emploi
4. **Inspecteurs du travail (`LABOR_INSPECTOR`)** - Agents publics surveillant la conformité
5. **Personnel Itou (`ITOU_STAFF`)** - Administrateurs de la plateforme

#### Règles Métier

**Champs Principaux du Modèle User :**
- `kind` : Champ obligatoire déterminant le type d'utilisateur (contraint en base de données)
- `email` : Unique, insensible à la casse (utilise CIEmailField), stocké comme NULL si vide
- `title` : Civilité (M/MME) - requis pour les demandeurs d'emploi
- `identity_provider` : Fournisseur SSO utilisé pour l'authentification
- `created_by` : Clé étrangère vers l'utilisateur ayant créé ce compte (pour création par procuration)
- `first_login` : Horodatage de la première connexion (auto-défini au premier `last_login`)
- `public_id` : UUID pour les URLs publiques et l'accès API

**Contraintes :**
- Seuls les utilisateurs `ITOU_STAFF` peuvent avoir `is_staff=True` ou `is_superuser=True`
- Chaque utilisateur doit avoir une valeur `kind` valide
- L'email doit être unique pour tous les utilisateurs (insensible à la casse)

**Création de Compte :**
- Les demandeurs d'emploi peuvent s'auto-inscrire ou être créés par des prescripteurs/employeurs (création par procuration)
- Les utilisateurs créés par procuration reçoivent un email d'activation avec lien magique
- Le nom d'utilisateur est auto-généré en utilisant UUID4 (non visible par l'utilisateur)

### 1.2 Authentification & Fournisseurs d'Identité

#### Fournisseurs d'Identité Supportés

1. **Django Natif (`DJANGO`)**
   - Disponible pour : Tous types d'utilisateurs
   - Authentification traditionnelle username/password
   - Vérification email obligatoire (via django-allauth)

2. **France Connect (`FC`)**
   - Disponible pour : Demandeurs d'emploi uniquement
   - Fournisseur d'identité gouvernemental pour les citoyens
   - Auto-remplit : first_name, last_name, birthdate

3. **PE Connect (`PEC`)** - Pôle emploi Connect
   - Disponible pour : Demandeurs d'emploi uniquement
   - Identité France Travail (ancien Pôle emploi)
   - Fournit l'accès aux données d'emploi

4. **ProConnect (`PC`)**
   - Disponible pour : Prescripteurs et employeurs
   - Fournisseur d'identité professionnel
   - Pour les professionnels du secteur public

5. **Inclusion Connect (`IC`)**
   - Statut : Plus supporté (héritage)
   - Données historiques conservées

#### Logique Métier d'Authentification

**Validation du Fournisseur d'Identité :**
```python
# Fichier : itou/users/models.py:421-432
def validate_identity_provider(self):
    if self.identity_provider == IdentityProvider.FRANCE_CONNECT and self.kind != UserKind.JOB_SEEKER:
        raise ValidationError("France connect n'est utilisable que par un candidat.")

    if self.identity_provider == IdentityProvider.PE_CONNECT and self.kind != UserKind.JOB_SEEKER:
        raise ValidationError("PE connect n'est utilisable que par un candidat.")

    if self.identity_provider == IdentityProvider.INCLUSION_CONNECT and self.kind not in [
        UserKind.PRESCRIBER, UserKind.EMPLOYER]:
        raise ValidationError("Inclusion connect n'est utilisable que par un prescripteur ou employeur.")
```

**Traçabilité des Sources de Données Externes :**
- `external_data_source_history` : Champ JSON traçant toutes les mises à jour depuis les fournisseurs SSO
- Chaque mise à jour enregistre : field_name, source, created_at, value
- Journal chronologique en ajout uniquement

### 1.3 Système de Profil Demandeur d'Emploi

#### Modèle JobSeekerProfile
Chaque demandeur d'emploi obtient automatiquement un profil (créé via signal de sauvegarde du modèle).

**Informations Personnelles :**
- `birthdate` : Requis pour l'ASP, validé
- `birth_place` : Commune (France) ou NULL
- `birth_country` : Clé étrangère Pays, requis si pas France
- Contrainte : Si France, birth_place requis ; si pas France, birth_place doit être NULL

**Sécurité Sociale & Identité :**
- `nir` : Numéro de sécurité sociale français (NIR), unique quand non vide
- `lack_of_nir_reason` : Explique l'absence (TEMPORARY_NUMBER, NO_NIR, NIR_ASSOCIATED_TO_OTHER)
- Contrainte : Ne peut avoir à la fois NIR et lack_of_nir_reason
- Validation NIR : La civilité doit correspondre au code genre du NIR, la date de naissance doit correspondre

**Intégration Service d'Emploi :**
- `pole_emploi_id` : Identifiant France Travail (8 ou 11 caractères)
- `lack_of_pole_emploi_id_reason` : ID ou raison requis (FORGOTTEN, NOT_REGISTERED)
- `pe_obfuscated_nir` : ID chiffré depuis l'API France Travail
- `pe_last_certification_attempt_at` : Horodatage de dernière vérification de certification
- `ft_gps_id` : Identifiant système GPS depuis le datalake France Travail

**Situation Administrative (pour l'ASP) :**
- `education_level` : Requis (codes 00-99 depuis l'ASP)
- `resourceless` : Booléen - sans ressources
- `rqth_employee` : Statut RQTH (reconnaissance handicap)
- `oeth_employee` : Statut OETH (obligation d'emploi travailleurs handicapés)
- `pole_emploi_since` : Durée d'inscription à France Travail
- `unemployed_since` : Durée sans emploi
- `has_rsa_allocation` : Statut RSA (NO, YES, YES_MONTHLY)
- `rsa_allocation_since`, `ass_allocation_since`, `aah_allocation_since` : Durées d'allocations
- `are_allocation_since`, `activity_bonus_since` : Allocations spécifiques EITI
- `cape_freelance`, `cesa_freelance` : Indicateurs bénéfices indépendants

**Adresse HEXA (format compatible ASP) :**
L'adresse du demandeur d'emploi doit être formatée en format HEXA pour le traitement ASP :
- `hexa_lane_number` : Numéro de voie
- `hexa_std_extension` : Extension standard (B, T, Q, C)
- `hexa_non_std_extension` : Extension non standard
- `hexa_lane_type` : Type de voie (depuis les choix LaneType de l'ASP)
- `hexa_lane_name` : Nom de voie (requis si un champ HEXA rempli)
- `hexa_additional_address` : Complément d'adresse
- `hexa_post_code` : Code postal (requis)
- `hexa_commune` : Référence commune INSEE (requis)

**Calcul d'Adresse :**
```python
# Fichier : itou/users/models.py:1325
def update_hexa_address(self):
    # Calcule le format HEXA depuis les champs d'adresse de User
    # Appelle l'API de géocodage inverse
    # Met à jour tous les champs hexa_*
    # Lève ValidationError si l'adresse ne peut être formatée
```

**Certification d'Identité :**
- `identity_certifications` : Many-to-many traçant les certifications
- Certificateurs : `API_FT_RECHERCHE_INDIVIDU_CERTIFIE`, `API_PARTICULIER`
- Les champs certifiés deviennent en lecture seule
- Si certifié par API Particulier, certains champs sont verrouillés

**Suivi Candidat Bloqué :**
- `is_stalled` : Indicateur auto-calculé
- `is_not_stalled_anymore` : Remplacement manuel
- Logique : Candidat avec candidature dans les 6 derniers mois, pas de candidature acceptée, première candidature >30 jours

### 1.4 Fonctionnalités de Compte Utilisateur

#### Gestion des Mots de Passe
- Minimum 14 caractères avec exigences de complexité
- Réinitialisation par email avec liens magiques à jeton
- Authentification à deux facteurs (OTP/TOTP) disponible pour les utilisateurs staff

#### Vérification Email
- Vérification email obligatoire (via django-allauth)
- Lien magique envoyé à l'email de l'utilisateur
- Propriété cachée `has_verified_email` vérifie l'état de vérification

#### Création d'Utilisateur par Procuration
Les demandeurs d'emploi peuvent être créés par des prescripteurs ou employeurs pour le compte de candidats :

```python
# Fichier : itou/users/models.py:695-725
@classmethod
def create_job_seeker_by_proxy(cls, proxy_user, acting_organization=None, gps=False, **fields):
    # Crée un demandeur d'emploi avec nom d'utilisateur aléatoire
    # Définit created_by au proxy_user
    # Envoie email d'activation avec lien de réinitialisation mot de passe
    # Retourne l'utilisateur créé
```

**Règles de Création par Procuration :**
- Champ `created_by` défini au créateur
- `is_handled_by_proxy` : Vrai si demandeur d'emploi créé par procuration et jamais connecté
- Le créateur peut éditer l'email si l'utilisateur n'a pas vérifié l'email
- Le profil demandeur d'emploi `created_by_prescriber_organization` trace l'organisation créatrice

#### Anonymisation Utilisateur (RGPD)
Les utilisateurs inactifs sont anonymisés après notification :
- `upcoming_deletion_notified_at` : Horodatage de l'avertissement de suppression
- Les utilisateurs professionnels peuvent être réactivés si :
  - `is_active=False`
  - A un fournisseur SSO et nom d'utilisateur
  - A `upcoming_deletion_notified_at` et pas d'email

#### Réactivation de Compte
```python
# Fichier : itou/users/models.py:536-548
def can_be_reactivated(self):
    if self.is_active:  # Déjà actif
        return False
    if self.kind not in UserKind.professionals():  # Limité aux professionnels
        return False
    if self.username and self.has_sso_provider:  # Connexion sera possible
        if self.upcoming_deletion_notified_at and not self.email:
            return True  # Anonymisé mais récupérable
    return False
```
