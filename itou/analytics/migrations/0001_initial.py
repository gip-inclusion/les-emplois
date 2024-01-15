import uuid

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Datum",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False)),
                (
                    "code",
                    models.TextField(
                        choices=[
                            ("ER-001", "FS totales"),
                            ("ER-002", "FS (probablement) supprimées"),
                            ("ER-101", "FS intégrées (0000) au premier retour"),
                            ("ER-102", "FS avec une erreur au premier retour"),
                            ("ER-102-3436", "FS avec une erreur 3436 au premier retour"),
                            ("ER-103", "FS ayant eu au moins un retour en erreur"),
                            ("AP-001", "PASS IAE total"),
                            ("AP-002", "PASS IAE annulés"),
                            ("AP-101", "PASS IAE synchronisés avec succès avec pole emploi"),
                            ("AP-102", "PASS IAE en attente de synchronisation avec pole emploi"),
                            ("AP-103", "PASS IAE en erreur de synchronisation avec pole emploi"),
                            ("AP-104", "PASS IAE prêts à être synchronisés avec pole emploi"),
                            ("US-001", "Nombre d'utilisateurs"),
                            ("US-011", "Nombre de demandeurs d'emploi"),
                            ("US-012", "Nombre de prescripteurs"),
                            ("US-013", "Nombre d'employeurs"),
                            ("US-014", "Nombre d'inspecteurs du travail"),
                            ("US-015", "Nombre d'administrateurs"),
                        ],
                    ),
                ),
                ("bucket", models.TextField()),
                ("value", models.IntegerField()),
                ("measured_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                "verbose_name_plural": "data",
            },
        ),
        migrations.AddIndex(
            model_name="datum",
            index=models.Index(fields=["measured_at", "code"], name="analytics_d_measure_a59c08_idx"),
        ),
        migrations.AlterUniqueTogether(
            name="datum",
            unique_together={("code", "bucket")},
        ),
    ]
