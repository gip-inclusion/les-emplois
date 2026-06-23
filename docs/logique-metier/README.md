# Les Emplois de l'Inclusion - Documentation Logique Métier

**Plateforme** : Plateforme numérique pour la gestion des PASS IAE (agréments d'emploi) et la mise en relation des employeurs inclusifs avec les demandeurs d'emploi
**Domaine** : IAE (Insertion par l'Activité Économique) - Système français d'emploi inclusif
**Dernière mise à jour** : 2025-11-18

---

## Vue d'ensemble

Cette documentation complète décrit la logique métier de la plateforme "Les Emplois de l'Inclusion". Elle couvre 16 domaines fonctionnels principaux et 5 annexes techniques.

---

## Table des matières

### Domaines Fonctionnels

1. **[Gestion des Utilisateurs & Authentification](01-utilisateurs-authentification.md)**
   - Système multi-rôles (5 types d'utilisateurs)
   - Fournisseurs d'identité (France Connect, PE Connect, ProConnect)
   - Profils demandeurs d'emploi et gestion d'identité

2. **[Gestion des Organisations](02-organisations.md)**
   - Structures SIAE (9 types)
   - Organisations de prescripteurs
   - Conventions, adhésions et relations

3. **[Système de Candidatures](03-candidatures.md)**
   - Cycle de vie des candidatures (8 états)
   - Processus de validation et approbation
   - Gestion des transitions d'état

4. **[Système d'Éligibilité & Agréments](04-eligibilite-agrements.md)**
   - Diagnostics d'éligibilité IAE
   - PASS IAE (agréments)
   - Suspensions et prolongations
   - Critères administratifs et d'éligibilité

5. **[Descriptions de Poste & Recrutement](05-offres-emploi.md)**
   - Fiches de poste et marché caché
   - Types de contrat et localisation
   - Catalogues ROME et compétences

6. **[Gestion des Fiches Salarié (ASP)](06-fiches-salarie-asp.md)**
   - Intégration ASP (Agence de Services et de Paiement)
   - Enregistrements employés et cycles de vie
   - Exigences de format HEXA pour adresses

7. **[Campagnes d'Évaluation & Contrôle](07-campagnes-evaluation.md)**
   - Campagnes de contrôle institutionnel
   - Soumissions et évaluations

8. **[Communication & Notifications](08-communication-notifications.md)**
   - Système de messagerie interne
   - Emails transactionnels
   - Templates et canaux de communication

9. **[Intégrations & APIs Externes](09-integrations-apis.md)**
   - API Pôle Emploi (France Travail)
   - API Entreprise (données SIRET)
   - API Géolocalisation
   - Webhooks et synchronisation

10. **[Tableaux de Bord & Reporting](10-tableaux-bord.md)**
    - Statistiques et métriques
    - Export de données
    - Vues personnalisées par rôle

11. **[GPS (Accompagnement Guidé & Suivi)](11-gps.md)**
    - Système de suivi des demandeurs d'emploi
    - Coordination entre acteurs

12. **[Recherche & Autocomplétion](12-recherche.md)**
    - Recherche plein texte (PostgreSQL)
    - API d'autocomplétion
    - Recherche géographique

13. **[Gestion des Fichiers](13-gestion-fichiers.md)**
    - Upload et stockage de documents
    - Validation et sécurité
    - Types de fichiers supportés

14. **[Fonctionnalités Administratives](14-admin.md)**
    - Interface d'administration Django
    - Gestion des données de référence
    - Outils de modération

15. **[Sécurité & Conformité](15-securite-conformite.md)**
    - RGPD et protection des données
    - Contrôles d'accès et permissions
    - Audit et traçabilité

16. **[Fonctionnalités Additionnelles](16-fonctionnalites-diverses.md)**
    - Gestion des villes et géographie
    - Données de référence
    - Utilitaires et helpers

---

### Annexes

- **[A. Résumé Règles Métier Clés](annexes/regles-metier.md)**
- **[B. Diagrammes Machine à États](annexes/machines-etats.md)**
- **[C. Résumé Points Terminaison API](annexes/api-endpoints.md)**
- **[D. Points Saillants Schéma Base Données](annexes/schema-bdd.md)**
- **[E. Glossaire](annexes/glossaire.md)**

---

## Guide de navigation

### Par type d'utilisateur

- **Demandeurs d'emploi** → [1](01-utilisateurs-authentification.md), [3](03-candidatures.md), [4](04-eligibilite-agrements.md), [11](11-gps.md)
- **Employeurs** → [2](02-organisations.md), [3](03-candidatures.md), [5](05-offres-emploi.md), [6](06-fiches-salarie-asp.md)
- **Prescripteurs** → [1](01-utilisateurs-authentification.md), [2](02-organisations.md), [4](04-eligibilite-agrements.md)
- **Administrateurs** → [14](14-admin.md), [15](15-securite-conformite.md), [7](07-campagnes-evaluation.md)

### Par processus métier

- **Recrutement** → [3](03-candidatures.md) → [4](04-eligibilite-agrements.md) → [6](06-fiches-salarie-asp.md)
- **Gestion PASS IAE** → [4](04-eligibilite-agrements.md) → [9](09-integrations-apis.md)
- **Intégration ASP** → [6](06-fiches-salarie-asp.md) → [9](09-integrations-apis.md)

---

## Contribuer

Pour mettre à jour cette documentation :

1. Identifiez le fichier de domaine concerné
2. Modifiez le fichier markdown approprié
3. Mettez à jour la date "Dernière mise à jour" dans ce README
4. Référencez les fichiers source dans le code (`file:line`)

---

**Version** : 1.0
**Plateforme** : Les Emplois de l'Inclusion
**Référentiel** : https://github.com/betagouv/itou
