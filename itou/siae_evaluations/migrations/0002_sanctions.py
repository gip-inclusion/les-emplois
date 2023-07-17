import django.core.validators
import django.db.models.deletion
from django.db import migrations, models

import itou.utils.models


class Migration(migrations.Migration):
    dependencies = [
        ("siae_evaluations", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Sanctions",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "training_session",
                    models.TextField(
                        blank=True,
                        verbose_name=(
                            "Détails de la participation à une session de présentation de l’auto-prescription"
                        ),
                    ),
                ),
                (
                    "suspension_dates",
                    itou.utils.models.InclusiveDateRangeField(
                        blank=True, null=True, verbose_name="Retrait de la capacité d’auto-prescription"
                    ),
                ),
                (
                    "subsidy_cut_percent",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        null=True,
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(100),
                        ],
                        verbose_name="Pourcentage de retrait de l’aide au poste",
                    ),
                ),
                (
                    "subsidy_cut_dates",
                    itou.utils.models.InclusiveDateRangeField(
                        blank=True, null=True, verbose_name="Dates de retrait de l’aide au poste"
                    ),
                ),
                (
                    "deactivation_reason",
                    models.TextField(blank=True, verbose_name="Explication du déconventionnement de la structure"),
                ),
                (
                    "no_sanction_reason",
                    models.TextField(blank=True, verbose_name="Explication de l’absence de sanction"),
                ),
                (
                    "evaluated_siae",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="siae_evaluations.evaluatedsiae",
                        verbose_name="SIAE évaluée",
                    ),
                ),
            ],
            options={"verbose_name_plural": "sanctions"},
        ),
        migrations.AddConstraint(
            model_name="sanctions",
            constraint=models.CheckConstraint(
                check=models.Q(
                    models.Q(("subsidy_cut_dates__isnull", True), ("subsidy_cut_percent__isnull", True)),
                    models.Q(("subsidy_cut_dates__isnull", False), ("subsidy_cut_percent__isnull", False)),
                    _connector="OR",
                ),
                name="subsidy_cut_consistency",
                violation_error_message=(
                    "Le pourcentage et la date de début de retrait de l’aide au poste doivent être renseignés."
                ),
            ),
        ),
    ]
