import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("files", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("companies", "0004_siaejobdescription_field_history"),
        ("prescribers", "0003_alter_prescribermembership_updated_at_and_more"),
        ("approvals", "0011_prepare_prolongation_for_inheritance"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProlongationRequest",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "start_at",
                    models.DateField(
                        db_index=True, default=django.utils.timezone.localdate, verbose_name="date de début"
                    ),
                ),
                (
                    "end_at",
                    models.DateField(
                        db_index=True, default=django.utils.timezone.localdate, verbose_name="date de fin"
                    ),
                ),
                (
                    "reason",
                    models.CharField(
                        choices=[
                            ("SENIOR_CDI", "CDI conclu avec une personne de plus de 57\u202fans"),
                            ("COMPLETE_TRAINING", "Fin d'une formation"),
                            ("RQTH", "RQTH - Reconnaissance de la qualité de travailleur handicapé"),
                            ("SENIOR", "50\u202fans et plus"),
                            (
                                "PARTICULAR_DIFFICULTIES",
                                "Difficultés particulièrement importantes dont l'absence de prise en charge ferait "
                                "obstacle à son insertion professionnelle",
                            ),
                            ("HEALTH_CONTEXT", "Contexte sanitaire"),
                        ],
                        default="COMPLETE_TRAINING",
                        max_length=30,
                        verbose_name="motif",
                    ),
                ),
                ("reason_explanation", models.TextField(blank=True, verbose_name="explications supplémentaires")),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now, verbose_name="date de création"),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="date de modification")),
                (
                    "require_phone_interview",
                    models.BooleanField(blank=True, default=False, verbose_name="demande d'entretien téléphonique"),
                ),
                ("contact_email", models.EmailField(blank=True, max_length=254, verbose_name="e-mail de contact")),
                (
                    "contact_phone",
                    models.CharField(blank=True, max_length=20, verbose_name="numéro de téléphone de contact"),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("PENDING", "À traiter"), ("GRANTED", "Acceptée"), ("DENIED", "Refusée")],
                        default="PENDING",
                        max_length=32,
                        verbose_name="statut",
                    ),
                ),
                ("processed_at", models.DateTimeField(blank=True, null=True, verbose_name="date de traitement")),
                (
                    "approval",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="approvals.approval", verbose_name="PASS IAE"
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)ss_created",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="créé par",
                    ),
                ),
                (
                    "declared_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)ss_declared",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="déclarée par",
                    ),
                ),
                (
                    "declared_by_siae",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="companies.siae",
                        verbose_name="SIAE du déclarant",
                    ),
                ),
                (
                    "prescriber_organization",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="prescribers.prescriberorganization",
                        verbose_name="organisation du prescripteur habilité",
                    ),
                ),
                (
                    "processed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)s_processed",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="traité par",
                    ),
                ),
                (
                    "report_file",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="files.file",
                        verbose_name="fichier bilan",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)ss_updated",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="modifié par",
                    ),
                ),
                (
                    "validated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)ss_validated",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="prescripteur habilité qui a autorisé cette prolongation",
                    ),
                ),
            ],
            options={
                "verbose_name": "demande de prolongation",
                "verbose_name_plural": "demandes de prolongation",
                "ordering": ["-created_at"],
                "abstract": False,
            },
        ),
        migrations.AddField(
            model_name="prolongation",
            name="request",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="approvals.prolongationrequest",
                verbose_name="demande de prolongation",
            ),
        ),
        migrations.AddConstraint(
            model_name="prolongationrequest",
            constraint=models.CheckConstraint(
                check=models.Q(
                    ("report_file", None),
                    models.Q(
                        ("reason__in", ("RQTH", "SENIOR", "PARTICULAR_DIFFICULTIES")), ("report_file__isnull", False)
                    ),
                    _connector="OR",
                ),
                name="check_prolongationrequest_reason_and_report_file_coherence",
                violation_error_message="Incohérence entre le fichier de bilan et la raison de prolongation",
            ),
        ),
        migrations.AddConstraint(
            model_name="prolongationrequest",
            constraint=models.CheckConstraint(
                check=models.Q(
                    ("require_phone_interview", False),
                    models.Q(
                        models.Q(("contact_email", ""), _negated=True), models.Q(("contact_phone", ""), _negated=True)
                    ),
                    _connector="OR",
                ),
                name="check_prolongationrequest_require_phone_interview",
            ),
        ),
        migrations.AddConstraint(
            model_name="prolongationrequest",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "PENDING")),
                fields=("approval",),
                name="unique_prolongationrequest_approval_for_pending",
                violation_error_message="Une demande de prolongation à traiter existe déjà pour ce PASS IAE",
            ),
        ),
    ]
