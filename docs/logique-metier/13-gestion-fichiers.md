# Gestion des Fichiers


### 13.1 Téléchargement & Stockage Fichiers

**Modèle File :**
- `key` : Clé S3/MinIO unique
- `created_at` : Horodatage téléchargement
- `preview` : Aperçu image pour documents

**Types Fichiers Supportés :**

1. **CV (`resume_link`) :**
   - Taille max : 5 Mo
   - Formats : PDF, DOC, DOCX, ODT
   - Lié à : JobApplication, profil User

2. **Rapport Prolongation (`report_file`) :**
   - Requis pour certains motifs prolongation
   - Formats : PDF
   - Lié à : ProlongationRequest, Prolongation

3. **Documents Preuve :**
   - Pour campagnes évaluation
   - Formats divers acceptés

**Backend Stockage :**
- Production : S3 (AWS ou compatible)
- Développement : MinIO (compatible S3)
- Fichiers privés : URLs signées avec expiration
- Fichiers publics : Accès direct

### 13.2 Scan Antivirus

**Intégration ClamAV :**

**Processus Scan :**
1. Fichier téléchargé vers stockage temporaire
2. Daemon ClamAV scanne fichier
3. Si propre : déplacer vers stockage permanent
4. Si infecté : rejeter téléchargement, journaliser incident

**Statut Scan :**
- `scan_pending` : Pas encore scanné
- `scan_clean` : Scan passé
- `scan_infected` : Virus détecté

**Scan Asynchrone :**
Fichiers scannés de manière asynchrone via tâches Huey pour gros fichiers.


