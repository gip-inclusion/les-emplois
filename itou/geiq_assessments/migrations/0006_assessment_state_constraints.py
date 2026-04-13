from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("geiq_assessments", "0005_assessment_state_assessmenttransitionlog"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="assessment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("state", "new"), ("submitted_at", None)),
                    models.Q(
                        ("submitted_at__isnull", False),
                        models.Q(("state", "new"), _negated=True),
                    ),
                    _connector="OR",
                ),
                name="geiq_assessment_state_submitted_at",
                violation_error_message="Impossible d'avoir de date de soumission si le statut est À compléter.",
            ),
        ),
        migrations.AddConstraint(
            model_name="assessment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("reviewed_at", None), ("state__in", ["new", "submitted"])),
                    models.Q(
                        ("reviewed_at__isnull", False),
                        ("state__in", ["reviewed", "final_reviewed"]),
                    ),
                    _connector="OR",
                ),
                name="geiq_assessment_state_reviewed_at",
                violation_error_message="Impossible d'avoir de date de contrôle si le statut est "
                "À compléter ou Envoyé.",
            ),
        ),
        migrations.AddConstraint(
            model_name="assessment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("final_reviewed_at", None),
                        models.Q(("state", "final_reviewed"), _negated=True),
                    ),
                    models.Q(
                        ("final_reviewed_at__isnull", False),
                        ("state", "final_reviewed"),
                    ),
                    _connector="OR",
                ),
                name="geiq_assessment_state_final_reviewed_at",
                violation_error_message="Impossible d'avoir de date de contrôle DREETS si le statut n'est "
                "pas Contrôlé (DREETS).",
            ),
        ),
    ]
