# Système d'Éligibilité & Agréments


### 4.1 Diagnostic d'Éligibilité IAE

#### Modèle EligibilityDiagnosis
Évalue l'éligibilité du demandeur d'emploi pour les programmes IAE.

**Champs Principaux :**
- `job_seeker` : FK vers demandeur d'emploi diagnostiqué
- `author` : FK vers utilisateur ayant créé le diagnostic
- `author_kind` : EMPLOYER ou PRESCRIBER
- `author_siae` ou `author_prescriber_organization` : Organisation de l'auteur
- `expires_at` : Date expiration diagnostic

**Logique de Validité :**
```python
# Un diagnostic est valide si :
- expires_at >= aujourd'hui
- job_seeker correspond
- for_siae correspond (si spécifique SIAE)
```

**Types de Diagnostics :**

1. **Diagnostic Prescripteur Habilité**
   - `author_kind = PRESCRIBER`
   - `author_prescriber_organization.is_authorized = True`
   - Peut outrepasser période carence PASS IAE
   - Validité : typiquement 6 mois

2. **Auto-Diagnostic Employeur**
   - `author_kind = EMPLOYER`
   - `author_siae` = SIAE diagnostiquante
   - Ne peut outrepasser période carence
   - Validité : typiquement 6 mois

#### AdministrativeCriteria
Système deux niveaux de critères :

**Critères Niveau 1** (indicateurs plus forts) :
- Chômage longue durée
- Résident logement social
- Parent isolé
- Etc.

**Critères Niveau 2** (facteurs additionnels) :
- Jeune sans diplôme
- Senior
- Handicap (RQTH/OETH)
- Etc.

**Sélection :**
- `SelectedAdministrativeCriteria` : Table intermédiaire M2M
- Lie diagnostic aux critères sélectionnés
- Suivi pour reporting et statistiques

#### Expiration Diagnostic
```python
# Calcul expiration par défaut
expires_at = created_at + timedelta(days=182)  # ~6 mois
```

**Priorité Dernier Diagnostic :**
Si plusieurs diagnostics valides existent, le plus récent est utilisé.

### 4.2 Diagnostic d'Éligibilité GEIQ

#### Modèle GEIQEligibilityDiagnosis
Diagnostic spécialisé pour structures GEIQ avec calcul allocation.

**Niveaux Critères GEIQ :**
- Critères Niveau 1 (Annexe 1 ou Les deux)
- Critères Niveau 2 (Annexe 2 ou Les deux)

**Règles d'Éligibilité Allocation :**
Une allocation est accordée si :
- Rédigé par prescripteur habilité, OU
- ≥1 critère Niveau 1 sélectionné, OU
- ≥2 critères Niveau 2 sélectionnés, OU
- ≥1 critère depuis Annexe 1 (ou Les deux)

**Action Préalable :**
- `prior_action` : Booléen indiquant si action préalable terminée
- Affecte détermination éligibilité finale

### 4.3 Gestion PASS IAE (Agréments)

#### Modèle Approval
Agrément d'emploi permettant aux demandeurs d'emploi de travailler en SIAE.

**Champs Principaux :**
- `number` : Numéro unique alphanumerique 12 caractères
- `user` : FK vers demandeur d'emploi
- `start_at`, `end_at` : Période de validité
- `created_by` : Utilisateur ayant créé l'agrément
- `origin` : Source agrément (DEFAULT, PE_APPROVAL, AI_STOCK, ADMIN)
- `eligibility_diagnosis` : FK vers diagnostic (si créé normalement)

**Format Numéro :**
- Créé par ITOU : `{ASP_ITOU_PREFIX}{numéro-7-chiffres}` (ex : `XXXXX0000001`)
- Importé PE : Format historique Pôle emploi

**Génération Numéro :**
```python
# Fichier : itou/approvals/models.py:867-905
@staticmethod
def get_next_number():
    # Verrouiller table pour empêcher conditions course
    # Obtenir max numéro depuis Approval et CancelledApproval
    next_number = max(Approval.last_number(), CancelledApproval.last_number()) + 1
    if next_number > 9999999:
        raise RuntimeError("Numéro maximum atteint")
    return f"{ASP_ITOU_PREFIX}{next_number:07d}"
```

**Durée :**
- Par défaut : 2 ans (730 jours)
- Maximum : 5 ans total (avec prolongations)
- `end_at` est inclusif (durée réelle = end_at - start_at + 1 jour)

**États (calculés) :**
- `FUTURE` : start_at > aujourd'hui
- `VALID` : start_at ≤ aujourd'hui ≤ end_at, pas suspendu
- `SUSPENDED` : Actuellement suspendu
- `EXPIRED` : end_at < aujourd'hui

### 4.4 Période de Carence Agrément

**Règle :** Après expiration d'un agrément, période carence 2 ans s'applique avant qu'un nouvel agrément puisse être délivré.

**Exceptions à la Période Carence :**
1. **Demande Prescripteur Habilité**
   - Organisation prescripteur a `authorization_status = VALIDATED`
   - Peut demander nouvel agrément immédiatement

2. **Diagnostic d'Éligibilité Valide**
   - Demandeur emploi a diagnostic valide depuis prescripteur habilité
   - Diagnostic pas expiré

**Implémentation :**
```python
# Fichier : itou/users/models.py:593-608
def new_approval_blocked_by_waiting_period(self, siae, sender_prescriber_organization):
    is_sent_by_authorized_prescriber = (
        sender_prescriber_organization is not None
        and sender_prescriber_organization.is_authorized
    )

    has_valid_diagnosis = self.has_valid_diagnosis()

    return (
        self.has_latest_approval_in_waiting_period
        and siae.is_subject_to_iae_rules
        and not (is_sent_by_authorized_prescriber or has_valid_diagnosis)
    )
```

### 4.5 Suspension d'Agrément

#### Modèle Suspension
Suspend temporairement un PASS IAE sans l'annuler.

**Motifs de Suspension :**
- `CONTRACT_SUSPENDED` : Contrat suspendu >15 jours
- `CONTRACT_BROKEN` : Contrat rompu
- `FINISHED_CONTRACT` : Contrat terminé
- `APPROVAL_BETWEEN_CTA_MEMBERS` : Accord comité CTA
- `CONTRAT_PASSERELLE` : Expérimentation contrat passerelle (EI/ACI uniquement)

**Motifs Historiques (plus disponibles) :**
- SICKNESS, MATERNITY, INCARCERATION, TRIAL_OUTSIDE_IAE, DETOXIFICATION, FORCE_MAJEURE

**Règles Métier :**

1. **Limites de Durée :**
   - Minimum : 1 jour
   - Maximum : 36 mois par suspension
   - Suspensions consécutives multiples autorisées

2. **Rétroactivité :**
   - Peut commencer jusqu'à 365 jours dans le passé (depuis date création)
   - Ne peut commencer dans le futur
   - Doit commencer dans limites agrément

3. **Prévention Chevauchement :**
   - ExclusionConstraint PostgreSQL empêche chevauchement suspensions
   - Utilise opérateur chevauchement plage sur [start_at, end_at]

4. **Levée Automatique Suspension :**
   - Quand nouvelle candidature acceptée avec même demandeur emploi
   - end_at suspension défini à hiring_start_at - 1 jour
   - Ou supprimée si embauche commence à date début suspension

5. **Extension Date Fin Agrément :**
   - Quand suspension créée : approval.end_at += (suspension.end_at - suspension.start_at)
   - Quand suspension mise à jour : approval.end_at ajusté en conséquence
   - Quand suspension supprimée : approval.end_at -= (suspension.end_at - suspension.start_at)
   - **Trigger PostgreSQL** gère cela automatiquement

**Qui Peut Suspendre :**
Seule la SIAE embauchant actuellement le demandeur emploi peut suspendre :
```python
def can_be_suspended_by_siae(self, siae):
    return self.can_be_suspended and last_hire_was_made_by_siae(self.user, siae)
```

#### Suspension vs. Prolongation
- **Suspension** : Met en pause agrément, étend date fin
- **Prolongation** : Étend agrément au-delà des 2 ans d'origine

### 4.6 Prolongation d'Agrément

#### Système Prolongation (Processus Deux Étapes)

**Étape 1 : ProlongationRequest**
SIAE déclare besoin de prolongation :

**Champs :**
- `approval` : FK vers agrément prolongé
- `start_at` : Doit égaler `approval.end_at`
- `end_at` : Nouvelle date fin demandée
- `reason` : Motif prolongation (voir ci-dessous)
- `status` : PENDING, GRANTED, DENIED
- `assigned_to` : Prescripteur habilité traitant demande
- `declared_by`, `declared_by_siae` : SIAE déclarant
- `prescriber_organization` : Organisation prescripteur (optionnel)
- `report_file` : Requis pour certains motifs
- `require_phone_interview` : Demande rappel
- `contact_email`, `contact_phone` : Infos contact

**Étape 2 : Prolongation**
Créée quand demande est GRANTED :

**Motifs & Règles Prolongation :**

| Motif | Max par Demande | Max Cumulé | Avis Prescripteur | Cas d'Usage |
|-------|----------------|------------|-------------------|-------------|
| `SENIOR_CDI` | 10 ans (3650 jours) | Pas de limite | Non | CDI Inclusion jusqu'à retraite |
| `COMPLETE_TRAINING` | 12 mois (365 jours) | Pas de limite | Non | Achèvement formation |
| `RQTH` | 12 mois (365 jours) | 3 ans (1095 jours) | Oui | Reconnaissance handicap |
| `SENIOR` | 12 mois (365 jours) | 5 ans (1825 jours) | Oui | Travailleur senior (50+) |
| `PARTICULAR_DIFFICULTIES` | 12 mois (365 jours) | 3 ans (1095 jours) | Oui | Difficultés particulières (AI/ACI uniquement) |

**Workflow Prolongation :**

1. **SIAE Crée Demande :**
   ```python
   prolongation_request = ProlongationRequest.objects.create(
       approval=approval,
       start_at=approval.end_at,  # Doit correspondre !
       end_at=approval.end_at + timedelta(days=365),
       reason=ProlongationReason.COMPLETE_TRAINING,
       declared_by=employer_user,
       declared_by_siae=siae,
       assigned_to=authorized_prescriber,
       # ... autres champs
   )
   # Notification envoyée au prescripteur habilité
   ```

2. **Prescripteur Révise :**
   - Peut accorder ou refuser
   - Si refusé, doit fournir motif et actions proposées

3. **Si Accordé :**
   ```python
   prolongation = prolongation_request.grant(prescriber_user)
   # Crée objet Prolongation
   # Définit request.status = GRANTED
   # Étend approval.end_at via trigger PostgreSQL
   # Envoie notifications SIAE et demandeur emploi
   ```

4. **Si Refusé :**
   ```python
   prolongation_request.deny(
       user=prescriber_user,
       information=ProlongationRequestDenyInformation(
           reason=DENY_REASON,
           reason_explanation="...",
           proposed_actions=[ACTION1, ACTION2],
           proposed_actions_explanation="..."
       )
   )
   # Définit request.status = DENIED
   # Envoie notifications SIAE et demandeur emploi
   ```

**Prévention Chevauchement Prolongation :**
- ExclusionConstraint PostgreSQL sur `(approval, date_range)`
- Utilise `[start_at, end_at)` (début inclusif, fin exclusive)
- Prolongations adjacentes autorisées (end_at₁ = start_at₂)

**Trigger pour Date Fin Agrément :**
Similaire suspension, trigger PostgreSQL étend automatiquement `approval.end_at` :
```sql
-- Au INSERT : approval.end_at += (prolongation.end_at - prolongation.start_at)
-- Au UPDATE : approval.end_at ajusté en conséquence
-- Au DELETE : approval.end_at -= (prolongation.end_at - prolongation.start_at)
```

### 4.7 Annulation d'Agrément

**Processus Annulation :**
Quand un agrément est supprimé, il devient un `CancelledApproval` :

```python
# Fichier : itou/approvals/models.py:549-581
def delete(self):
    # Créer CancelledApproval avec données anonymisées
    CancelledApproval(
        start_at=self.start_at,
        end_at=self.start_at,  # Annulé = start == end pour Pôle emploi
        number=self.number,
        user_last_name=self.user.last_name,
        user_first_name=self.user.first_name,
        user_nir=self.user.jobseeker_profile.nir,
        user_birthdate=self.user.jobseeker_profile.birthdate,
        user_id_national_pe=self.user.jobseeker_profile.pe_obfuscated_nir,
        origin_siae_siret=siae_siret,
        origin_siae_kind=siae_kind,
        origin_sender_kind=sender_kind,
        origin_prescriber_organization_kind=prescriber_kind,
    ).save()

    # Délier des candidatures
    self.jobapplication_set.update(approval=None)

    # Réellement supprimer
    super().delete()
```

**CancelledApproval :**
- Préserve numéro agrément et données utilisateur
- Permet notification à Pôle emploi
- Ne peut être restauré (irréversible)

### 4.8 Intégration Pôle Emploi (Notifications Agrément)

#### Processus Notification

**Pour Agréments Actifs :**
1. **Certification (si nécessaire) :**
   ```python
   id_national = pe_client.recherche_individu_certifie(
       first_name=user.first_name,
       last_name=user.last_name,
       nir=user.jobseeker_profile.nir,
       birthdate=user.jobseeker_profile.birthdate,
   )
   # Stocke comme pe_obfuscated_nir
   # Crée enregistrement IdentityCertification
   ```

2. **Mise à Jour PASS IAE :**
   ```python
   pe_client.mise_a_jour_pass_iae(
       approval,
       id_national_pe,
       siae_siret,
       siae_kind,
       origine_candidature,
       typologie_prescripteur,
   )
   ```

**États Notification :**
- `PENDING` : Pas encore envoyé ou attend conditions
- `SHOULD_RETRY` : Erreur temporaire, réessayera
- `ERROR` : Erreur permanente, intervention manuelle nécessaire
- `SUCCESS` : Envoyé avec succès à Pôle emploi

**Vérifications Préliminaires (Sauter Notification Si) :**
- Agrément commence dans futur
- Données utilisateur manquantes (nom, NIR, date naissance)
- Type SIAE invalide
- Aucune candidature acceptée trouvée

**Traitement Asynchrone :**
- Notifications envoyées via file tâches Huey
- Tâche cron traite notifications en attente
- Logique nouvelle tentative pour erreurs récupérables


