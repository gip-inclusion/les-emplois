# Campagnes d'Évaluation & Contrôle


### 7.1 Campagnes d'Évaluation SIAE

#### Modèle EvaluationCampaign
Campagnes contrôle pour surveiller conformité SIAE.

**Champs Campagne :**
- `name` : Nom campagne
- `institution` : FK vers institution contrôle (inspection travail)
- `calendar_id` : Identifiant calendrier unique
- `percent_auto_prescription_suspension` : % pénalité suspension auto-prescription

**SIAE Évaluée :**
- Table intermédiaire `EvaluatedSiae` lie campagnes aux entreprises
- `reviewed_at` : Quand évaluation terminée
- `sanctions_set` : Sanctions liées si non conforme

#### Système Sanction

**Modèle Sanction :**
- `evaluated_siae` : FK vers SIAE évaluée
- `suspension_dates` : Plage dates suspension
- `reason` : Motif sanction

**Suspension Auto-Prescription :**
Quand sanctionnée pendant période suspension active :
- SIAE ne peut auto-délivrer PASS IAE
- Doit demander agrément manuel via prescripteur habilité
- Pénalité basée pourcentage (depuis campagne)

**Soumission Révision :**
SIAE peut soumettre documents révision :
- Télécharger documents preuve
- Fournir justifications
- Demander levée révision

### 7.2 Évaluation Label GEIQ

#### Modèle GEIQAssessment
Évaluation spécifique conformité label GEIQ.

**Champs Évaluation :**
- `campaign` : FK vers campagne évaluation
- `geiq` : FK vers entreprise GEIQ
- `assessment_status` : Statut évaluation

**Intégration API Label GEIQ :**
- Système validation label GEIQ externe
- Point terminaison API pour soumission évaluation
- Mises à jour statut automatisées


