# Recherche & Autocomplétion


### 12.1 Système Recherche Globale

**Fonctionnalité Recherche :**

1. **Recherche Entreprise :**
   - Recherche texte intégral sur nom, description
   - Filtrage géographique (ville, distance)
   - Filtrage catégorie métier
   - Filtrage statut actif/embauche

2. **Recherche Description Poste :**
   - Par titre poste (appellation)
   - Par localisation
   - Par type entreprise

3. **Recherche Prescripteur :**
   - Par nom
   - Par type
   - Par statut habilitation

**Technologie Recherche :**
- Recherche texte intégral PostgreSQL avec `SearchVector`
- Index GIN pour performance
- Config `simple_unaccent` (insensible accents)

**Exemple :**
```python
# Recherche utilisateur
search_query = SearchQuery(name, config="simple_unaccent")
users = User.objects.filter(full_name_search_vector=search_query)
users = users.annotate(rank=SearchRank("full_name_search_vector", search_query))
users = users.order_by("-rank")
```

### 12.2 Fonctionnalités Autocomplétion

**Points Terminaison Autocomplétion :**

1. **Autocomplétion Ville :**
   - Utilise modèle `cities.City`
   - Retourne : nom ville, code postal, département
   - Ordonné par population

2. **Autocomplétion Entreprise :**
   - Entreprises actives uniquement
   - Retourne : SIRET, nom, ville
   - Pour sélection employeur

3. **Autocomplétion Appellation Métier :**
   - Code ROME et libellé
   - Retourne : code, appellation
   - Pour recherche emploi

4. **Autocomplétion Organisation Prescripteur :**
   - Nom organisation, type
   - Pour sélectionner prescripteur

5. **Autocomplétion Recherche Utilisateur :**
   - Par nom complet
   - Restreint utilisateurs autorisés
   - Pour opérations admin/staff

**Implémentation :**
- Utilise plugin jQuery select2
- Requêtes AJAX vers vues autocomplétion
- Support pagination
- Longueur requête minimum (typiquement 2-3 caractères)


