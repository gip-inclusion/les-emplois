from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("job_applications", "0008_alter_jobapplication_approval_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="jobapplication",
            name="archived_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True, verbose_name="archivée le"),
        ),
        migrations.AddField(
            model_name="jobapplication",
            name="archived_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.RESTRICT,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
                verbose_name="archivée par",
            ),
        ),
        migrations.AddConstraint(
            model_name="jobapplication",
            constraint=models.CheckConstraint(
                check=models.Q(
                    ("archived_at__isnull", False), ("state__in", ["accepted", "prior_to_hire"]), _negated=True
                ),
                name="archived_status",
                violation_error_message=(
                    "Impossible d’archiver une candidature acceptée ou en action préalable à l’embauche."
                ),
            ),
        ),
        migrations.AddConstraint(
            model_name="jobapplication",
            constraint=models.CheckConstraint(
                check=models.Q(("archived_at", None), ("archived_by__isnull", False), _negated=True),
                name="archived_by__no_archived_at",
                violation_error_message="Une candidature active ne peut pas avoir été archivée par un utilisateur.",
            ),
        ),
    ]
