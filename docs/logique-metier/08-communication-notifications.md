# Communication & Notifications


### 8.1 Système Notification Email

#### Templates Email & Déclencheurs

**Notifications Candidature :**

1. **Candidature Soumise :**
   - À : Employeur (tous membres actifs)
   - Déclencheur : Candidature créée
   - Template : `job_applications/emails/new_for_employer_*.txt`

2. **Candidature Acceptée :**
   - À : Demandeur emploi
   - Déclencheur : Candidature acceptée
   - Template : `job_applications/emails/accept_for_job_seeker_*.txt`
   - À : Prescripteur (si applicable)
   - Template : `job_applications/emails/accept_for_prescriber_*.txt`

3. **Candidature Refusée :**
   - À : Demandeur emploi
   - Déclencheur : Candidature refusée
   - Inclut motif refus

4. **Candidature Annulée :**
   - À : Demandeur emploi
   - Déclencheur : Candidature acceptée annulée

**Notifications Agrément :**

1. **PASS IAE Délivré :**
   - À : Employeur
   - Déclencheur : Agrément créé
   - Template : `approvals/emails/delivered_to_employer_*.txt`
   - Inclut : Numéro agrément, période validité

2. **Demande Agrément Manuel :**
   - À : Équipe support Itou
   - Déclencheur : Candidature nécessite agrément manuel
   - Raison : Données manquantes, diagnostic expiré, etc.

**Notifications Prolongation :**

1. **Demande Créée :**
   - À : Prescripteur habilité assigné
   - Déclencheur : ProlongationRequest créée

2. **Demande Accordée :**
   - À : SIAE (declared_by)
   - À : Demandeur emploi
   - Déclencheur : Demande accordée par prescripteur

3. **Demande Refusée :**
   - À : SIAE (declared_by)
   - À : Demandeur emploi
   - Déclencheur : Demande refusée
   - Inclut : Motif refus et actions proposées

**Notifications Système :**

1. **Activation Compte :**
   - À : Nouvel utilisateur
   - Déclencheur : Utilisateur créé (auto-inscription ou procuration)
   - Inclut : Lien magique activation

2. **Réinitialisation Mot de Passe :**
   - À : Utilisateur demandant réinitialisation
   - Lien magique à jeton

3. **Avertissement Suppression Prochaine :**
   - À : Utilisateur inactif
   - Déclencheur : Utilisateur inactif période prolongée
   - Timing : Avant anonymisation

### 8.2 Traitement Email Asynchrone

**File Tâches Huey :**
Tous emails envoyés de manière asynchrone pour éviter blocage requête :

```python
from itou.utils.emails import send_email_async

send_email_async(
    to=[email],
    context=context,
    subject_template=subject,
    body_template=body,
)
```

**Logique Nouvelle Tentative :**
- Max nouvelles tentatives : 3
- Backoff exponentiel
- Journalisation erreurs vers Sentry

### 8.3 Préférences Notification

#### Modèle NotificationSettings
Préférences notification par structure :

**Champs :**
- `structure_type` : ContentType Company ou PrescriberOrganization
- `structure_pk` : ID organisation
- `disabled_notifications` : Tableau clés notification désactivées

**Options Opt-Out :**
Utilisateurs peuvent désactiver types notification spécifiques :
- Emails candidature
- Annonces système
- Mises à jour fonctionnalités


