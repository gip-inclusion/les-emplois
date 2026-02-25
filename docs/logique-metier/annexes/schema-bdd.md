# Points Saillants Schéma Base Données


### Contraintes Clés

**Contraintes Unicité :**
1. `users_user` : Email unique (insensible casse, NULL pour vide)
2. `jobseekerprofile` : NIR unique (quand pas vide)
3. `approvals_approval` : Numéro unique
4. `employee_record_employeerecord` : Unique (asp_measure, siret, approval_number)
5. `companies_company` : Unique (siret, kind)

**Contraintes Vérification :**
1. `users_user` : Seulement ITOU_STAFF peut être staff/superuser
2. `jobseekerprofile` : Ne peut avoir à la fois NIR et lack_of_nir_reason
3. `jobseekerprofile` : Cohérence pays/lieu naissance
4. `approvals_approval` : start_at < end_at
5. `approvals_prolongation` : Cohérence motif/fichier rapport

**Contraintes Exclusion :**
1. `approvals_suspension` : Empêcher chevauchement plages dates suspension
2. `approvals_prolongation` : Empêcher chevauchement plages dates prolongation

### Triggers Clés

**Triggers PostgreSQL :**

1. **`approvals_suspension.update_approval_end_at` :**
   - Sur INSERT/UPDATE/DELETE suspension
   - Ajuste automatiquement `approval.end_at`

2. **`approvals_prolongation.update_approval_end_at` :**
   - Sur INSERT/UPDATE/DELETE prolongation
   - Ajuste automatiquement `approval.end_at`

3. **`approvals_approval.create_employee_record_notification` :**
   - Sur UPDATE dates agrément
   - Crée `EmployeeRecordUpdateNotification` pour enregistrements PROCESSED

4. **`approvals_approval.plan_pe_notification_on_date_updates` :**
   - Sur UPDATE dates agrément
   - Réinitialise `pe_notification_status` à PENDING

5. **`users_jobseekerprofile_fields_history` :**
   - Trace changements `asp_uid`, `is_not_stalled_anymore`

6. **`companies_company_fields_history` :**
   - Trace changements `siret`

### Index Clés

**Index GIN (Recherche Texte Intégral) :**
- `users_user.full_name_search_vector`

**Index B-tree :**
- `users_user.email` (insensible casse via OpClass)
- `jobseekerprofile.birthdate`
- `approvals_approval.start_at`, `end_at`
- `employee_record_employeerecord.siret`

**Index GiST (Géographique) :**
- `companies_company.coords`
- `cities_city.coords`


