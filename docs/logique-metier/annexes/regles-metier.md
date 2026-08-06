# Résumé Règles Métier Clés


### Règles Agrément (PASS IAE)

1. **Durée Par Défaut :** 2 ans (730 jours)
2. **Durée Totale Maximum :** 5 ans (avec prolongations)
3. **Période Carence :** 2 ans après expiration (exceptions prescripteurs habilités)
4. **Suspension :** Max 36 mois par suspension, suspensions consécutives illimitées
5. **Prolongation :** Règles diverses par motif (voir section 4.6)
6. **Format Numéro :** `{ASP_ITOU_PREFIX}{7-chiffres-séquentiels}`

### Règles Candidature

1. **Auto-Refus :** Après 60 jours dans NEW ou PROCESSING
2. **Auto-Obsolescence :** Quand demandeur emploi accepte autre candidature
3. **Exigences Acceptation :** Doit avoir hiring_start_at
4. **Transitions État :** Journalisées avec timestamp et utilisateur

### Règles Fiche Salarié

1. **Éligibilité :** Seulement pour ACI, AI, EI, EITI, ETTI
2. **Unicité :** (asp_measure, siret, approval_number)
3. **Validation :** Adresse HEXA complète requise
4. **Auto-Archivage :** 6 mois après expiration agrément + 1 mois grâce
5. **Notifications Mise à Jour :** Auto-générées sur changements dates agrément

### Règles Activation Entreprise

1. **SIAE IAE :** Active seulement si a convention active
2. **GEIQ/EA/EATT/OPCS :** Toujours actives
3. **Créées Staff :** Toujours actives (temporaire)
4. **Période Grâce :** 30 jours après désactivation convention

### Règles Compte Utilisateur

1. **Mot de Passe :** Minimum 14 caractères
2. **Vérification Email :** Obligatoire tous utilisateurs
3. **Anonymisation :** Après 2 ans inactivité (demandeurs emploi)
4. **SSO :** Fournisseur identité doit correspondre type utilisateur


