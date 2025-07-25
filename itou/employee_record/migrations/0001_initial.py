# Generated by Django 5.2.4 on 2025-07-19 05:14

import django.db.models.deletion
import django.utils.timezone
import django_xworkflows.models
from django.conf import settings
from django.db import migrations, models

import itou.employee_record.models
import itou.utils.validators


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("companies", "0001_initial"),
        ("job_applications", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EmployeeRecord",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now, verbose_name="date de création"),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="date de modification")),
                (
                    "status",
                    django_xworkflows.models.StateField(
                        max_length=10,
                        verbose_name="statut",
                        workflow=django_xworkflows.models._SerializedWorkflow(
                            initial_state="NEW",
                            name="EmployeeRecordWorkflow",
                            states=["NEW", "READY", "SENT", "REJECTED", "PROCESSED", "DISABLED", "ARCHIVED"],
                        ),
                    ),
                ),
                ("approval_number", models.CharField(max_length=12, verbose_name="numéro d'agrément")),
                ("asp_id", models.PositiveIntegerField(verbose_name="identifiant ASP de la SIAE")),
                (
                    "asp_processing_code",
                    models.CharField(max_length=4, null=True, verbose_name="code de traitement ASP"),
                ),
                (
                    "archived_json",
                    models.JSONField(blank=True, null=True, verbose_name="archive JSON de la fiche salarié"),
                ),
                (
                    "job_application",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="employee_record",
                        to="job_applications.jobapplication",
                        verbose_name="candidature / embauche",
                    ),
                ),
                (
                    "financial_annex",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="companies.siaefinancialannex",
                        verbose_name="annexe financière",
                    ),
                ),
                (
                    "asp_batch_line_number",
                    models.IntegerField(null=True, verbose_name="ligne correspondante dans le fichier batch ASP"),
                ),
                (
                    "asp_batch_file",
                    models.CharField(
                        max_length=27,
                        null=True,
                        validators=[itou.employee_record.models.validate_asp_batch_filename],
                        verbose_name="fichier de batch ASP",
                    ),
                ),
                ("processed_at", models.DateTimeField(null=True, verbose_name="date d'intégration")),
                (
                    "siret",
                    models.CharField(
                        db_index=True,
                        max_length=14,
                        validators=[itou.utils.validators.validate_siret],
                        verbose_name="siret structure mère",
                    ),
                ),
                (
                    "asp_processing_label",
                    models.CharField(max_length=200, null=True, verbose_name="libellé de traitement ASP"),
                ),
                ("processed_as_duplicate", models.BooleanField(default=False, verbose_name="déjà intégrée par l'ASP")),
                (
                    "asp_measure",
                    models.CharField(
                        choices=[
                            ("ACI_DC", "Droit Commun - Atelier et Chantier d'Insertion"),
                            ("AI_DC", "Droit Commun - Association Intermédiaire"),
                            ("EI_DC", "Droit Commun -  Entreprise d'Insertion"),
                            ("EITI_DC", "Droit Commun - Entreprise d'Insertion par le Travail Indépendant"),
                            ("ETTI_DC", "Droit Commun - Entreprise de Travail Temporaire d'Insertion"),
                            ("ACI_MP", "Milieu Pénitentiaire - Atelier et Chantier d'Insertion"),
                            ("EI_MP", "Milieu Pénitentiaire - Entreprise d'Insertion"),
                            ("FDI_DC", "Droit Commun -  Fonds Départemental pour l'Insertion"),
                        ],
                        verbose_name="mesure ASP de la SIAE",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "verbose_name": "fiche salarié",
                "verbose_name_plural": "fiches salarié",
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("asp_batch_file__isnull", False)),
                        fields=("asp_batch_file", "asp_batch_line_number"),
                        name="unique_employeerecord_asp_batch_file_and_line",
                    ),
                    models.UniqueConstraint(
                        fields=("asp_measure", "siret", "approval_number"),
                        name="unique_asp_measure_siret_approval_number",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="EmployeeRecordUpdateNotification",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now, verbose_name="date de création"),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="date de modification")),
                (
                    "status",
                    django_xworkflows.models.StateField(
                        max_length=10,
                        verbose_name="statut",
                        workflow=django_xworkflows.models._SerializedWorkflow(
                            initial_state="NEW",
                            name="EmployeeRecordUpdateNotificationWorkflow",
                            states=["NEW", "SENT", "PROCESSED", "REJECTED"],
                        ),
                    ),
                ),
                (
                    "asp_processing_code",
                    models.CharField(max_length=4, null=True, verbose_name="code de traitement ASP"),
                ),
                (
                    "asp_processing_label",
                    models.CharField(max_length=200, null=True, verbose_name="libellé de traitement ASP"),
                ),
                (
                    "asp_batch_file",
                    models.CharField(
                        max_length=27,
                        null=True,
                        validators=[itou.employee_record.models.validate_asp_batch_filename],
                        verbose_name="fichier de batch ASP",
                    ),
                ),
                (
                    "asp_batch_line_number",
                    models.IntegerField(null=True, verbose_name="ligne correspondante dans le fichier batch ASP"),
                ),
                (
                    "employee_record",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="update_notifications",
                        to="employee_record.employeerecord",
                        verbose_name="fiche salarié",
                    ),
                ),
                (
                    "archived_json",
                    models.JSONField(blank=True, null=True, verbose_name="archive JSON de la fiche salarié"),
                ),
            ],
            options={
                "verbose_name": "notification de changement de la fiche salarié",
                "verbose_name_plural": "notifications de changement de la fiche salarié",
                "ordering": ["-created_at"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("asp_batch_file__isnull", False)),
                        fields=("asp_batch_file", "asp_batch_line_number"),
                        name="unique_employeerecordupdatenotification_asp_batch_file_and_line",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("status", "NEW")),
                        fields=("employee_record",),
                        name="unique_new_employee_record",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="EmployeeRecordTransitionLog",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("transition", models.CharField(db_index=True, max_length=255, verbose_name="transition")),
                ("from_state", models.CharField(db_index=True, max_length=255, verbose_name="from state")),
                ("to_state", models.CharField(db_index=True, max_length=255, verbose_name="to state")),
                (
                    "timestamp",
                    models.DateTimeField(
                        db_index=True, default=django.utils.timezone.now, verbose_name="performed at"
                    ),
                ),
                (
                    "asp_processing_code",
                    models.CharField(max_length=4, null=True, verbose_name="code de traitement ASP"),
                ),
                (
                    "asp_processing_label",
                    models.CharField(max_length=200, null=True, verbose_name="libellé de traitement ASP"),
                ),
                (
                    "asp_batch_file",
                    models.CharField(
                        max_length=27,
                        null=True,
                        validators=[itou.employee_record.models.validate_asp_batch_filename],
                        verbose_name="fichier de batch ASP",
                    ),
                ),
                (
                    "asp_batch_line_number",
                    models.IntegerField(null=True, verbose_name="ligne correspondante dans le fichier batch ASP"),
                ),
                (
                    "archived_json",
                    models.JSONField(blank=True, null=True, verbose_name="archive JSON de la fiche salarié"),
                ),
                (
                    "employee_record",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="logs",
                        to="employee_record.employeerecord",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "recovered",
                    models.BooleanField(
                        default=False, editable=False, verbose_name="récupéré rétroactivement avec un script"
                    ),
                ),
            ],
            options={
                "verbose_name": "log des transitions de la fiche salarié",
                "verbose_name_plural": "log des transitions des fiches salarié",
                "ordering": ["-timestamp"],
                "abstract": False,
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("asp_batch_file__isnull", False)),
                        fields=("asp_batch_file", "asp_batch_line_number"),
                        name="unique_employeerecordtransitionlog_asp_batch_file_and_line",
                    )
                ],
            },
        ),
    ]
