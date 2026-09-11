# GPS (Accompagnement Guidé & Suivi)


### 11.1 Groupes Suivi

**Objectif :** Suivre demandeurs emploi dans système GPS (Accompagnement Guidé & Suivi)

**Modèle FollowUpGroup :**
- `beneficiary` : FK vers demandeur emploi
- `followup_group_members` : Organisations suivant le bénéficiaire
- Intégration datalake France Travail
- `gps_id` : Identifiant dans système France Travail

**Logique Métier :**
- Organisations prescripteur habilitées peuvent accéder groupes GPS
- Organisations multiples peuvent suivre même bénéficiaire
- Synchronisé avec datalake France Travail

**Points Intégration :**
- Créé quand demandeur emploi entre programme GPS
- Mis à jour via API France Travail
- Affiché dans tableau bord prescripteur


