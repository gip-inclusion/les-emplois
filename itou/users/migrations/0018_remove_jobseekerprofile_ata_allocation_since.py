from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0017_add_hijack_permission"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.AlterField(
                    model_name="jobseekerprofile",
                    name="ata_allocation_since",
                    field=models.CharField(
                        blank=True,
                        choices=[
                            ("01", "Moins de 6 mois"),
                            ("02", "De 6 à 11 mois"),
                            ("03", "De 12 à 23 mois"),
                            ("04", "24 mois et plus"),
                        ],
                        max_length=2,
                        verbose_name="allocataire de l'ATA depuis",
                        null=True,  # Make it nullable
                    ),
                )
            ],
            state_operations=[
                migrations.RemoveField(
                    model_name="jobseekerprofile",
                    name="ata_allocation_since",
                )
            ],
        ),
    ]
