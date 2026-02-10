import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Task",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("data", models.BinaryField()),
                (
                    "priority",
                    models.BigIntegerField(blank=True, null=True, verbose_name="priorité"),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now,
                        verbose_name="date de création",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(models.F("created_at"), name="created_at_idx"),
                    models.Index(
                        models.F("priority"),
                        condition=models.Q(("priority__isnull", False)),
                        name="priority_not_null_idx",
                    ),
                ],
            },
        ),
    ]
