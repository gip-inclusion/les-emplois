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
