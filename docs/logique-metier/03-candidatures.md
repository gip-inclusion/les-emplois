# Système de Candidatures


### 3.1 Machine à États Candidature

#### États (JobApplicationState)

1. **NEW** - Nouvelle candidature
   - État initial lors soumission candidature
   - En attente de revue employeur

2. **PROCESSING** - Candidature à l'étude
   - Employeur révise activement candidature
   - État transitionnel avant décision

3. **POSTPONED** - Candidature en attente
   - Candidature reportée pour revue ultérieure
   - Pas refusée, mais pas activement traitée

4. **PRIOR_TO_HIRE** - Action préalable à l'embauche
   - État spécifique GEIQ
   - Préparation contrat avant acceptation formelle

5. **ACCEPTED** - Candidature acceptée
   - Candidature acceptée, embauche confirmée
   - Déclenche logique création PASS IAE
   - Définit `hiring_start_at` et `hiring_end_at`

6. **REFUSED** - Candidature déclinée
   - Candidature rejetée
   - Nécessite `refusal_reason`

7. **CANCELLED** - Embauche annulée
   - Candidature précédemment acceptée annulée
   - Peut seulement transitionner depuis ACCEPTED

8. **OBSOLETE** - Embauché ailleurs
   - Candidat embauché ailleurs
   - Auto-défini quand autre candidature acceptée

9. **POOL** - Vivier de candidatures
   - Vivier de talents pour opportunités futures
   - Pas activement traitée

### 3.2 Transitions d'État

#### Workflow (JobApplicationWorkflow)

**Transitions Disponibles :**

| Transition | Depuis États | Vers État |
|------------|-------------|----------|
| `process` | NEW, POOL | PROCESSING |
| `postpone` | NEW, POOL, PROCESSING, PRIOR_TO_HIRE | POSTPONED |
| `accept` | NEW, POOL, PROCESSING, POSTPONED, PRIOR_TO_HIRE, OBSOLETE, REFUSED, CANCELLED | ACCEPTED |
| `add_to_pool` | NEW, PROCESSING, POSTPONED, CANCELLED, OBSOLETE | POOL |
| `move_to_prior_to_hire` | NEW, POOL, PROCESSING, POSTPONED, OBSOLETE, REFUSED, CANCELLED | PRIOR_TO_HIRE |
| `cancel_prior_to_hire` | PRIOR_TO_HIRE | PROCESSING |
| `refuse` | NEW, POOL, PROCESSING, PRIOR_TO_HIRE, POSTPONED | REFUSED |
| `cancel` | ACCEPTED | CANCELLED |
| `render_obsolete` | NEW, PROCESSING, POSTPONED | OBSOLETE |
| `transfer` | CAN_BE_TRANSFERRED_STATES | NEW |
| `reset` | OBSOLETE | NEW |
| `external_transfer` | REFUSED | REFUSED |

**Journalisation Transitions :**
Toutes les transitions journalisées dans `JobApplicationTransitionLog` :
- timestamp, from_state, to_state, transition, user

### 3.3 Logique Soumission Candidature

#### Qui Peut Soumettre des Candidatures ?

1. **Demandeur d'Emploi (auto-candidature)**
   - `sender_kind = JOB_SEEKER`
   - `sender = job_seeker`
   - `sender_company = NULL`
   - `sender_prescriber_organization = NULL`

2. **Prescripteur (pour compte demandeur d'emploi)**
   - `sender_kind = PRESCRIBER`
   - `sender = prescriber_user`
   - `sender_prescriber_organization = prescriber_org`
   - Peut inclure diagnostic d'éligibilité

3. **Employeur (créant candidature pour candidat)**
   - `sender_kind = EMPLOYER`
   - `sender = employer_user`
   - `sender_company = employer_company`

#### Types de Candidatures

**Candidature Spontanée :**
- `selected_jobs` = vide
- Entreprise doit avoir `spontaneous_applications_open_since != NULL`
- Périodes d'ouverture 90 jours

**Candidature Ciblée :**
- `selected_jobs` = un ou plusieurs objets JobDescription
- Candidature à postes spécifiques

#### Champs Requis

**Minimum :**
- `job_seeker` : FK vers candidat
- `to_company` : FK vers entreprise destinataire
- `sender`, `sender_kind` : Qui a soumis
- `state` : Par défaut NEW

**Optionnel mais Important :**
- `message` : Lettre motivation candidature
- `resume_link` : FK vers fichier CV téléchargé
- `eligibility_diagnosis` : FK vers diagnostic (si applicable)
- `geiq_eligibility_diagnosis` : FK vers diagnostic GEIQ
- `answer` : Message réponse employeur

### 3.4 Logique Création PASS IAE (à l'Acceptation)

Quand une candidature est acceptée, le système crée ou utilise automatiquement un PASS IAE :

```python
# Pseudo-code depuis logique transition
def accept_transition(job_application):
    # 1. Validation
    if not job_application.hiring_start_at:
        raise ValidationError("Impossible d'accepter sans date début embauche")

    # 2. Vérifier agrément existant valide
    if job_application.job_seeker.has_valid_approval:
        approval = job_application.job_seeker.latest_approval
    else:
        # 3. Vérifier période carence
        if job_application.job_seeker.has_latest_approval_in_waiting_period:
            # Peut seulement créer si prescripteur habilité ou diagnostic valide
            if not (is_authorized_prescriber or has_valid_diagnosis):
                raise ValidationError("Période carence bloque nouvel agrément")

        # 4. Créer nouvel agrément
        approval = Approval.objects.create(
            user=job_application.job_seeker,
            start_at=job_application.hiring_start_at,
            end_at=get_default_end_date(hiring_start_at),  # +2 ans
            origin_siae_siret=job_application.to_company.siret,
            origin_siae_kind=job_application.to_company.kind,
            origin_sender_kind=job_application.sender_kind,
            origin_prescriber_organization_kind=prescriber_org.kind,
            eligibility_diagnosis=job_application.eligibility_diagnosis,
        )

    # 5. Lier agrément à candidature
    job_application.approval = approval

    # 6. Lever suspension agrément si nécessaire
    if approval.is_suspended and approval.can_be_unsuspended:
        approval.unsuspend(job_application.hiring_start_at)

    # 7. Rendre autres candidatures obsolètes
    other_applications = JobApplication.objects.filter(
        job_seeker=job_application.job_seeker,
        state__in=[NEW, PROCESSING, POSTPONED]
    ).exclude(pk=job_application.pk)

    for app in other_applications:
        app.render_obsolete()

    # 8. Envoyer notifications
    notify_job_seeker(job_application)
    notify_prescriber(job_application)
    notify_pole_emploi(approval)  # Async
```

#### Logique Spécifique GEIQ

Les candidatures GEIQ ont champs additionnels :
- `prehiring_guidance_days` : Jours d'accompagnement pré-embauche
- `nb_hours_per_week` : Heures par semaine (1-48)
- `planned_training_hours` : Heures formation
- `inverted_vae_contract` : Indicateur VAE inversé
- `contract_type_details` : Détails contrat (APPRENTICESHIP, PROFESSIONAL_TRAINING, OTHER)
- `qualification_type` : Type de qualification
- `qualification_level` : Niveau qualification
- `prior_action` : Lien vers saisie action préalable

### 3.5 Fonctionnalités Auto-Traitement

#### Auto-Refus
Candidatures en états NEW ou PROCESSING pendant >60 jours sont auto-refusées :

```python
# Fichier : itou/job_applications/enums.py:153
AUTO_REJECT_JOB_APPLICATION_DELAY = datetime.timedelta(days=60)
```

**Processus :**
1. Tâche cron identifie candidatures périmées
2. Transitions vers état REFUSED
3. Définit `refusal_reason = RefusalReason.AUTO`
4. Envoie notification au candidat

#### Auto-Obsolescence
Quand une candidature est acceptée, toutes les autres candidatures en attente pour même demandeur d'emploi deviennent OBSOLETE.

#### Archivage Candidature
Les employeurs peuvent archiver manuellement candidatures dans états terminaux :
- REFUSED, CANCELLED, OBSOLETE (après envoi réponse)


