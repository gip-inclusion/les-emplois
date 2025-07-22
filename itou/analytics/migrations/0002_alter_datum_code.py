from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="datum",
            name="code",
            field=models.TextField(
                choices=[
                    ("ER-001", "FS totales"),
                    ("ER-002", "FS (probablement) supprimées"),
                    ("ER-101", "FS intégrées (0000) au premier retour"),
                    ("ER-102", "FS avec une erreur au premier retour"),
                    ("ER-102-3436", "FS avec une erreur 3436 au premier retour"),
                    ("ER-103", "FS ayant eu au moins un retour en erreur"),
                    ("AP-001", "PASS\xa0IAE total"),
                    ("AP-002", "PASS\xa0IAE annulés"),
                    ("AP-101", "PASS\xa0IAE synchronisés avec succès avec pole emploi"),
                    (
                        "AP-102",
                        "PASS\xa0IAE en attente de synchronisation avec pole emploi",
                    ),
                    (
                        "AP-103",
                        "PASS\xa0IAE en erreur de synchronisation avec pole emploi",
                    ),
                    (
                        "AP-104",
                        "PASS\xa0IAE prêts à être synchronisés avec pole emploi",
                    ),
                    ("US-001", "Nombre d'utilisateurs"),
                    ("US-011", "Nombre de demandeurs d'emploi"),
                    ("US-012", "Nombre de prescripteurs"),
                    ("US-013", "Nombre d'employeurs"),
                    ("US-014", "Nombre d'inspecteurs du travail"),
                    ("US-015", "Nombre d'administrateurs"),
                    ("API-001", "API : total d'appels reçus"),
                    ("API-002", "API : total de visiteurs uniques"),
                    ("API-003", "API candidats : total d'appels reçus"),
                    ("API-004", "API candidats : total de visiteurs uniques"),
                    ("API-005", "API GEIQ : total d'appels reçus"),
                    ("API-006", "API GEIQ : total de jetons uniques"),
                    ("API-007", "API FS : total d'appels reçus"),
                    ("API-008", "API FS : total de visiteurs uniques"),
                    ("API-009", "API Le marché : total d'appels reçus"),
                    ("API-010", "API siaes : total d'appels reçus"),
                    (
                        "API-011",
                        "API siaes : total de visiteurs uniques (par adresse IP)",
                    ),
                    ("API-012", "API structures : total d'appels reçus"),
                    ("API-013", "API candidatures : total d'appels reçus"),
                    ("API-014", "API candidatures : total de jetons uniques"),
                    ("SENTRY-001", "Apdex"),
                    ("SENTRY-002", "Taux de requêtes en échec"),
                    ("UPDOWN-001", "Taux de disponibilité"),
                    ("UPDOWN-002", "Apdex"),
                    ("GITHUB-001", "Total des PR de correctifs fusionnées aujourd'hui"),
                    ("ARCH-001", "Archive : Nombre de professionnels anonymisés"),
                    (
                        "ARCH-002",
                        "Archive : Nombre de professionnels anonymisés non supprimés",
                    ),
                    ("ARCH-003", "Archive : Nombre de demandeurs d'emploi anonymisés"),
                    ("ARCH-004", "Archive : Nombre de candidatures anonymisées"),
                    ("ARCH-005", "Archive : Nombre de PASS IAE anonymisés"),
                    ("ARCH-006", "Archive : Nombre de PASS IAE annulés anonymisés"),
                    (
                        "ARCH-007",
                        "Archive : Nombre de diagnostics d'éligibilité IAE anonymisés",
                    ),
                    (
                        "ARCH-008",
                        "Archive : Nombre de diagnostics d'éligibilité GEIQ anonymisés",
                    ),
                    ("ARCH-009", "Archive : Nombre de demandeurs d'emploi notifiés"),
                    ("ARCH-010", "Archive : Nombre de professionnels notifiés"),
                    ("ARCH-011", "Archive : Nombre de demandeurs d'emploi notifiables"),
                    ("ARCH-012", "Archive : Nombre de professionnels notifiables"),
                ]
            ),
        ),
    ]
