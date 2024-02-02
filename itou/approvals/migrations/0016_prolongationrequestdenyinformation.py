import django.contrib.postgres.fields
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0015_alter_suspension_updated_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProlongationRequestDenyInformation",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "reason",
                    models.CharField(
                        choices=[
                            ("IAE", "L’IAE ne correspond plus aux besoins / à la situation de la personne."),
                            (
                                "SIAE",
                                "La typologie de SIAE ne correspond plus aux besoins / à la situation de la personne.",
                            ),
                            (
                                "DURATION",
                                "La durée de prolongation demandée n’est pas adaptée à la situation du candidat.",
                            ),
                            (
                                "REASON",
                                "Le motif de prolongation demandé n’est pas adapté à la situation du candidat.",
                            ),
                        ],
                        verbose_name="motif de refus",
                    ),
                ),
                ("reason_explanation", models.TextField(verbose_name="explications du motif de refus")),
                (
                    "proposed_actions",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(
                            choices=[
                                (
                                    "EXIT_IAE",
                                    "Accompagnement à la recherche d’emploi hors IAE et mobilisation de l’offre de "
                                    "services disponible au sein de votre structure ou celle d’un partenaire.",
                                ),
                                (
                                    "SOCIAL_PARTNER",
                                    "Orientation vers un partenaire de l’accompagnement social/professionnel.",
                                ),
                                ("OTHER", "Autre"),
                            ]
                        ),
                        blank=True,
                        null=True,
                        size=None,
                        verbose_name="actions envisagées",
                    ),
                ),
                (
                    "proposed_actions_explanation",
                    models.TextField(blank=True, verbose_name="explications des actions envisagées"),
                ),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now, verbose_name="date de création"),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="date de modification")),
                (
                    "request",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="deny_information",
                        to="approvals.prolongationrequest",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="prolongationrequestdenyinformation",
            constraint=models.CheckConstraint(
                check=models.Q(("proposed_actions__len", 0), _negated=True),
                name="non_empty_proposed_actions",
                violation_error_message="Les actions envisagées ne peuvent pas être vide",
            ),
        ),
    ]
