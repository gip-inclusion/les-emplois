# Fonctionnalités Administratives


### 14.1 Interface Admin Django

**Personnalisations :**

1. **Vues Liste Améliorées :**
   - Filtres personnalisés (par état, date, région)
   - Actions groupées
   - Export vers CSV

2. **Édition En Ligne :**
   - Éditer objets liés en ligne
   - StackedInline et TabularInline

3. **Actions Personnalisées :**
   - Délivrance agrément groupée
   - Transitions fiche salarié groupées
   - Export/import données

4. **Champs Lecture Seule :**
   - Champs auto-calculés
   - Données historiques
   - Données source externe (ASP, GEIQ)

**Permissions Admin :**
- Groupe `itou-admin` : Accès complet
- Permissions spécialisées pour opérations spécifiques

### 14.2 Outils Réservés Staff

**Usurpation Identité Utilisateur (Hijack) :**
- Permission : `users.hijack`
- Permet au staff de voir plateforme comme autre utilisateur
- Piste audit journalisée

**Opérations Agrément Manuel :**
- Permission : `approvals.handle_manual_approval_requests`
- Délivrer agréments quand auto-création bloquée
- Outrepasser période carence

**Demandes Modification NIR :**
- Staff peut réviser et approuver changements NIR
- Modèle `NirModificationRequest`
- Notifications email équipe support

**Vérifications Qualité Données :**
- Détection incohérences
- Recherche doublons
- Outils nettoyage données

### 14.3 Import/Export Données

**Sources Import :**

1. **Import ASP (`import_siae.py`) :**
   - Mises à jour hebdomadaires données SIAE
   - Sync convention et annexe financière
   - Mises à jour SIRET

2. **Import GEIQ :**
   - Données structure GEIQ
   - Informations membres

3. **Import EA/EATT :**
   - Données entreprise adaptée

4. **Import Employés AI :**
   - Données historiques employés AI

5. **Import Agréments :**
   - Agréments historiques Pôle emploi
   - Conversion vers PASS IAE

**Capacités Export :**

1. **Export Fiche Salarié :**
   - Vers ASP (fichiers lot JSON)
   - Transfert SFTP

2. **Export Fichier CTA :**
   - Permission : `users.export_cta`
   - Pour inspection travail
   - Contient données embauche et agrément

3. **Export Statistiques :**
   - Format CSV
   - Plages dates personnalisées
   - Données agrégées


