# Résumé Points Terminaison API


### API REST Publique (DRF)

**URL Base :** `/api/v1/`

**Points Terminaison SIAE :**
- `GET /siaes/` - Lister SIAE actives
- `GET /siaes/{pk}/` - Détails SIAE
- `GET /siaes/search/` - Recherche géographique

**Points Terminaison Candidature (API Partenaire) :**
- `POST /job-applications/` - Créer candidature
- `GET /job-applications/{pk}/` - Détails candidature
- `PATCH /job-applications/{pk}/` - Mettre à jour candidature

**Points Terminaison Candidat :**
- `POST /applicants/` - Créer demandeur emploi
- `GET /applicants/{pk}/` - Détails demandeur emploi

**Points Terminaison Fiche Salarié (ASP) :**
- `GET /employee-records/` - Lister fiches salarié
- `GET /employee-records/{pk}/` - Détails fiche salarié

**Points Terminaison GEIQ :**
- Points terminaison spécifiques GEIQ pour gestion contrat

**Authentification :**
- Basée jeton (Authentification Jeton DRF)
- Débit limité

**Documentation :**
- Schéma OpenAPI (via DRF Spectacular)
- `/api/schema/` - Point terminaison schéma
- `/api/docs/` - Interface Swagger


