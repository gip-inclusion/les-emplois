from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0001_initial"),
        ("companies", "0001_initial"),
        ("eligibility", "0001_initial"),
        ("files", "0001_initial"),
        ("job_applications", "0001_initial"),
        ("prescribers", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="jobapplication",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("sender_kind", "employer"), _negated=True),
                    models.Q(
                        ("sender_company__isnull", False),
                        ("sender_kind", "employer"),
                        ("sender_prescriber_organization", None),
                    ),
                    _connector="OR",
                ),
                name="employer_sender_coherence",
                violation_error_message="Données incohérentes pour une candidature employeur",
            ),
        ),
        migrations.AddConstraint(
            model_name="jobapplication",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("sender_kind", "prescriber"), _negated=True),
                    models.Q(("sender_company", None), ("sender_kind", "prescriber")),
                    _connector="OR",
                ),
                name="prescriber_sender_coherence",
                violation_error_message="Données incohérentes pour une candidature prescripteur",
            ),
        ),
    ]
