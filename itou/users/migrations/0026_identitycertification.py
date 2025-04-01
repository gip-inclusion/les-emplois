import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0025_jobseekerprofile_fields_history"),
    ]

    operations = [
        migrations.CreateModel(
            name="IdentityCertification",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "certifier",
                    models.CharField(
                        choices=[
                            ("api_recherche_individu_certifie", "API France Travail recherche individu certifié"),
                            ("api_particulier", "API Particulier"),
                        ],
                        max_length=32,
                    ),
                ),
                ("certified_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "jobseeker_profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="identity_certifications",
                        to="users.jobseekerprofile",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        models.F("jobseeker_profile"), models.F("certifier"), name="uniq_jobseeker_profile_certifier"
                    )
                ],
            },
        ),
    ]
