# Sécurité & Conformité


### 15.1 Fonctionnalités Sécurité

**Sécurité Authentification :**

1. **Politique Mot de Passe :**
   - Minimum 14 caractères
   - Exigences complexité (vérifiées par validateurs auth django)
   - Pas mots de passe communs
   - Pas similarité aux données personnelles

2. **Sécurité Session :**
   - Timeout inactivité 1 semaine
   - Cookies sécurisés (HttpOnly, Secure)
   - Protection CSRF

3. **Authentification Deux Facteurs :**
   - OTP/TOTP pour utilisateurs staff
   - Optionnel pour prescripteurs/employeurs

**Contrôle Accès :**

1. **Système Permissions :**
   - Framework permissions Django
   - Permissions personnalisées pour opérations spécialisées
   - Accès basé groupe (itou-admin, etc.)

2. **Permissions Niveau Objet :**
   - Peut seulement voir données propre organisation
   - Employeurs : candidatures propre entreprise
   - Prescripteurs : demandeurs emploi propre organisation

**Sécurité Réseau :**

1. **Application HTTPS :**
   - Tout trafic sur HTTPS
   - En-têtes HSTS

2. **Politique Sécurité Contenu :**
   - En-têtes CSP restrictifs
   - Empêche attaques XSS

3. **Limitation Débit :**
   - Tentatives connexion
   - Requêtes API
   - Soumissions formulaires

### 15.2 Conformité RGPD

**Droits Sujet Données :**

1. **Droit Accès :**
   - Utilisateurs peuvent télécharger leurs données
   - Fonctionnalité export données

2. **Droit Rectification :**
   - Utilisateurs peuvent mettre à jour leurs données
   - Demandes modification NIR

3. **Droit Effacement :**
   - Anonymisation après inactivité
   - Anonymisation annulation agrément
   - Avertissements `upcoming_deletion_notified_at`

**Minimisation Données :**
- Collecter seulement données nécessaires
- Objectif clair pour chaque champ
- Politiques rétention

**Protection Données :**

1. **Chiffrement :**
   - Au repos : Chiffrement base données
   - En transit : HTTPS/TLS

2. **Pseudonymisation :**
   - `pe_obfuscated_nir` au lieu NIR brut pour appels API
   - UUIDs `public_id` pour URLs publiques

3. **Journalisation Accès :**
   - Pistes audit pour opérations sensibles
   - Journalisation actions utilisateur

**Processus Anonymisation :**

1. **Anonymisation Demandeur Emploi :**
   - Après 2 ans inactivité
   - Notification email avant
   - Remplace : email, first_name, last_name, phone
   - Garde : ID anonyme, stats emploi

2. **Anonymisation Professionnel :**
   - Après inactivité prolongée
   - Définit : email=NULL, is_active=False
   - Peut être réactivé via SSO

3. **Anonymisation Agrément :**
   - À annulation : données utilisateur copiées vers CancelledApproval
   - Agrément original supprimé

### 15.3 Audit & Traçabilité

**Mécanismes Audit :**

1. **Journaux Transitions :**
   - `JobApplicationTransitionLog`
   - `EmployeeRecordTransitionLog`
   - Capture : timestamp, user, from_state, to_state

2. **Historique Champs :**
   - ArrayField `fields_history` sur modèles clés
   - Trace changements champs critiques
   - Basé trigger PostgreSQL
   - Exemple : Changements SIRET sur Company

3. **Suivi Création :**
   - `created_by` sur plupart modèles
   - Trace qui a créé enregistrement
   - RESTRICT à suppression (pour responsabilité)

4. **Suivi Mise à Jour :**
   - `updated_by` sur modèles nécessitant
   - Horodatage auto `updated_at`

**Suivi Source Données :**
- `external_data_source_history` sur User
- Trace mises à jour données SSO
- Journal chronologique ajout uniquement


