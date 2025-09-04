import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("companies", "0008_contract"),
        ("siae_evaluations", "0003_evaluatedsiae_final_state"),
    ]

    operations = [
        migrations.CreateModel(
            name="ArchivedEvaluatedSiae",
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
                (
                    "reviewed_at",
                    models.DateTimeField(blank=True, null=True, editable=False, verbose_name="contrôlée le"),
                ),
                (
                    "final_reviewed_at",
                    models.DateTimeField(blank=True, null=True, editable=False, verbose_name="contrôle définitif le"),
                ),
                (
                    "final_state",
                    models.CharField(
                        blank=True,
                        choices=[("ACCEPTED", "Accepted"), ("REFUSED", "Refused")],
                        null=True,
                        editable=False,
                        verbose_name="état final après la cloture de la campagne d'évaluation",
                    ),
                ),
                (
                    "job_applications_count",
                    models.SmallIntegerField(editable=False, verbose_name="nombre d'autoprescription contrôlées"),
                ),
                (
                    "evaluation_campaign",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="archived_evaluated_siaes",
                        to="siae_evaluations.evaluationcampaign",
                        verbose_name="contrôle",
                    ),
                ),
                (
                    "siae",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="archived_evaluated_siaes",
                        to="companies.company",
                        verbose_name="SIAE",
                    ),
                ),
            ],
            options={
                "verbose_name": "entreprise contrôlée archivée",
                "verbose_name_plural": "entreprises contrôlées archivées",
                "unique_together": {("evaluation_campaign", "siae")},
            },
        ),
    ]
