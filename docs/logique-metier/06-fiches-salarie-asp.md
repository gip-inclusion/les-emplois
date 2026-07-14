# Gestion des Fiches Salarié (ASP)


### 6.1 Système Fiche Salarié

#### Objectif
Les fiches salarié (FS) transmettent données embauche à l'ASP (Agence de Services et de Paiement) pour traitement financier.

**Entreprises Éligibles :**
Seules ACI, AI, EI, EITI, ETTI peuvent créer fiches salarié.

#### Modèle EmployeeRecord

**Champs Principaux :**
- `job_application` : FK vers candidature acceptée (source toutes données)
- `financial_annex` : FK vers SiaeFinancialAnnex (sélectionné par utilisateur)
- `approval_number` : Numéro PASS IAE (dupliqué depuis job_application.approval)
- `asp_id` : Identifiant ASP SIAE (déprécié)
- `asp_measure` : Mesure ASP SIAE (depuis convention)
- `siret` : SIRET structure (peut différer de job_application.to_company.siret si antenne)

**Machine à États (EmployeeRecordWorkflow) :**

```
           ┌──> [NEW] ──────┐
           │       │         │
     enable│    ready        │ ready
           │       ↓         │
           └── [READY] ──────┘
                 │
        wait_for_asp_response
                 ↓
              [SENT]
               /   \
        process│   │reject
               │   │
               ↓   ↓
         [PROCESSED] [REJECTED]
               │   │   │
            disable  │ ready
               │   │   │
               ↓   ↓   ↓
            [DISABLED]
                 │
              archive
                 ↓
            [ARCHIVED]
               /  |  \
  unarchive_new/  |   \unarchive_rejected
               │  │    │
               ↓  ↓    ↓
             NEW  PROCESSED  REJECTED
```

**États :**
- `NEW` : Créée, nécessite révision
- `READY` : Validée, prête à envoyer à ASP
- `SENT` : Soumise à ASP, attend réponse
- `PROCESSED` : Traitée avec succès par ASP
- `REJECTED` : Rejetée par ASP avec code erreur
- `DISABLED` : Temporairement désactivée (pas envoyée)
- `ARCHIVED` : Archivée (agrément expiré)

**Transitions :**
- `ready` : Valider et marquer prêt (depuis NEW, REJECTED, DISABLED, PROCESSED)
- `wait_for_asp_response` : Envoyer à ASP (depuis READY)
- `process` : Marquer comme traité (depuis SENT)
- `reject` : Marquer comme rejeté (depuis SENT)
- `disable` : Désactiver enregistrement (depuis NEW, REJECTED, PROCESSED)
- `enable` : Réactiver (depuis DISABLED)
- `archive` : Archiver (depuis NEW, READY, REJECTED, PROCESSED, DISABLED)
- `unarchive_*` : Restaurer depuis archive

### 6.2 Traitement par Lots ASP

#### Génération Fichier Lot

**Format Fichier :**
- Nom : `RIAE_FS_AAAAMMJJHHMMSS.json` (exactement 27 caractères)
- Contenu : Tableau JSON fiches salarié
- Chaque enregistrement assigné numéro ligne

**Création Lot :**
1. Sélectionner enregistrements employés READY
2. Sérialiser chaque enregistrement en JSON (format spécifique ASP)
3. Assigner nom fichier lot et numéros ligne
4. Télécharger vers SFTP ASP
5. Mettre à jour enregistrements : status=SENT, asp_batch_file, asp_batch_line_number

#### Traitement Retour Lot

**Fichier Retour :**
ASP retourne résultats traitement :
```json
{
  "fichierTraite": "RIAE_FS_20231115120000.json",
  "lignes": [
    {
      "numeroLigne": 1,
      "codeTraitement": "0000",
      "libelleTraitement": "Traitement OK",
      ...
    },
    ...
  ]
}
```

**Codes Traitement :**
- `0000` : Succès
- `3436` : Doublon (déjà connu par ASP)
- Autre : Codes erreur divers

**Gestion Retour :**
1. Télécharger fichier retour depuis SFTP
2. Parser JSON
3. Faire correspondre enregistrements par `(asp_batch_file, asp_batch_line_number)`
4. Mettre à jour chaque enregistrement :
   - Succès (0000) : transition vers PROCESSED
   - Doublon (3436) : peut être forcé à PROCESSED (indicateur `processed_as_duplicate`)
   - Erreur : transition vers REJECTED avec détails erreur

### 6.3 Validation Fiche Salarié

#### Validation Pré-Envoi

**Vérifications Candidature :**
- Doit être état ACCEPTED
- Doit avoir agrément lié
- Indicateur `create_employee_record` doit être True

**Données Demandeur Emploi :**
- Civilité (M/MME) requise
- Niveau éducation requis
- NIR ou lack_of_nir_reason requis
- ID Pole emploi ou raison absence requis
- Adresse HEXA complète requise
- Tous champs obligatoires ASP remplis

**Vérifications Entreprise :**
- Convention doit exister
- Doit avoir annexe financière valide sélectionnée
- SIRET doit être valide (14 chiffres)
- Mesure ASP doit être définie

**Vérification Unicité :**
Empêche doublons :
```sql
UNIQUE (asp_measure, siret, approval_number)
```

#### Validation Adresse HEXA
Fiche salarié nécessite adresse demandeur emploi en format HEXA :
- `hexa_lane_type` (obligatoire)
- `hexa_lane_name` (obligatoire)
- `hexa_post_code` (obligatoire)
- `hexa_commune` (obligatoire)

Si pas rempli, employeur doit déclencher mise à jour adresse :
```python
job_seeker.jobseeker_profile.update_hexa_address()
```

### 6.4 Notifications Mise à Jour Fiche Salarié

#### Détection Automatique Mise à Jour

**Trigger :** Trigger PostgreSQL sur table `approvals_approval`

Quand dates agrément changent (start_at ou end_at) :
1. Trouver tous enregistrements employé PROCESSED/SENT/DISABLED avec cet agrément
2. Créer/mettre à jour `EmployeeRecordUpdateNotification` pour chacun

**EmployeeRecordUpdateNotification :**
- `employee_record` : FK vers fiche salarié
- `status` : NEW, SENT, PROCESSED, REJECTED
- Contrainte unique sur `(employee_record, status=NEW)` (une seule notification en attente)

**Processus Notification Mise à Jour :**
1. Notification créée/mise à jour (via trigger)
2. Tâche cron trouve notifications NEW
3. Génère fichier lot mise à jour (Type Mouvement = UPDATE)
4. Envoie à ASP
5. Traite retour
6. Met à jour statut notification

**Format JSON Notification :**
Similaire création, mais :
```json
{
  "typeMouvement": "UPDATE",
  "passIae": {
    "numero": "...",
    "dateDebut": "...",  // Mis à jour
    "dateFin": "...",    // Mis à jour
  },
  // Autres champs inchangés
}
```

### 6.5 Archivage Fiche Salarié

#### Logique Auto-Archivage

Fiches salarié auto-archivées si :
- `status != ARCHIVED`
- Agrément lié invalide (expiré)
- `created_at < maintenant - 6 mois` (période grâce)
- `updated_at < maintenant - 1 mois` (période grâce mise à jour récente)

**Processus Archive :**
1. Tâche cron s'exécute quotidiennement
2. Trouve enregistrements archivables (voir critères ci-dessus)
3. Transitions chacun vers état ARCHIVED
4. Sérialise données enregistrement vers `archived_json`

**Notifications Manquées :**
Lors désarchivage, vérifier si agrément prolongé/suspendu pendant archivé :
```python
last_employee_record_snapshot = max(
    employee_record.updated_at,
    max(update_notifications.created_at)
)

if last_employee_record_snapshot < approval.updated_at:
    # Créer notification mise à jour manquée
```


