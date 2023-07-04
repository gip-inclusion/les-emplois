import django.contrib.postgres.constraints
import django.contrib.postgres.fields.ranges
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import itou.utils.models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("approvals", "0009_suspension_cannot_start_in_the_future"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="prolongation",
            name="exclude_overlapping_prolongations",
        ),
        migrations.RemoveConstraint(
            model_name="prolongation",
            name="reason_report_file_coherence",
        ),
        migrations.AlterField(
            model_name="prolongation",
            name="created_by",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="%(class)ss_created",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Créé par",
            ),
        ),
        migrations.AlterField(
            model_name="prolongation",
            name="declared_by",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="%(class)ss_declared",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Déclarée par",
            ),
        ),
        migrations.AlterField(
            model_name="prolongation",
            name="updated_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="%(class)ss_updated",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Modifié par",
            ),
        ),
        migrations.AlterField(
            model_name="prolongation",
            name="validated_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="%(class)ss_validated",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Prescripteur habilité qui a autorisé cette prolongation",
            ),
        ),
        migrations.AddConstraint(
            model_name="prolongation",
            constraint=django.contrib.postgres.constraints.ExclusionConstraint(
                expressions=(
                    (
                        itou.utils.models.DateRange(
                            "start_at",
                            "end_at",
                            django.contrib.postgres.fields.ranges.RangeBoundary(
                                inclusive_lower=True, inclusive_upper=False
                            ),
                        ),
                        "&&",
                    ),
                    ("approval", "="),
                ),
                name="exclude_prolongation_overlapping_dates",
            ),
        ),
        migrations.AddConstraint(
            model_name="prolongation",
            constraint=models.CheckConstraint(
                check=models.Q(
                    ("report_file", None),
                    models.Q(
                        ("reason__in", ("RQTH", "SENIOR", "PARTICULAR_DIFFICULTIES")), ("report_file__isnull", False)
                    ),
                    _connector="OR",
                ),
                name="check_prolongation_reason_and_report_file_coherence",
                violation_error_message="Incohérence entre le fichier de bilan et la raison de prolongation",
            ),
        ),
    ]
