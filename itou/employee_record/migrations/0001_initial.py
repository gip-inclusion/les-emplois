# Generated by Django 5.0.3 on 2024-03-22 10:41

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

import itou.employee_record.models
import itou.utils.validators


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("companies", "0001_initial"),
        ("job_applications", "0001_initial"),
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
                    models.CharField(
                        choices=[
                            ("NEW", "Nouvelle"),
                            ("READY", "Complétée"),
                            ("SENT", "Envoyée"),
                            ("REJECTED", "En erreur"),
                            ("PROCESSED", "Intégrée"),
                            ("DISABLED", "Désactivée"),
                            ("ARCHIVED", "Archivée"),
                        ],
                        default="NEW",
                        max_length=10,
                        verbose_name="statut",
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
                "unique_together": set(),
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
                    models.CharField(
                        choices=[
                            ("NEW", "Nouvelle"),
                            ("SENT", "Envoyée"),
                            ("PROCESSED", "Intégrée"),
                            ("REJECTED", "En erreur"),
                        ],
                        default="NEW",
                        max_length=10,
                        verbose_name="statut",
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
            },
        ),
        migrations.AddConstraint(
            model_name="employeerecord",
            constraint=models.UniqueConstraint(
                condition=models.Q(("asp_batch_file__isnull", False)),
                fields=("asp_batch_file", "asp_batch_line_number"),
                name="unique_employeerecord_asp_batch_file_and_line",
            ),
        ),
        migrations.AddConstraint(
            model_name="employeerecordupdatenotification",
            constraint=models.UniqueConstraint(
                condition=models.Q(("asp_batch_file__isnull", False)),
                fields=("asp_batch_file", "asp_batch_line_number"),
                name="unique_employeerecordupdatenotification_asp_batch_file_and_line",
            ),
        ),
        migrations.AddConstraint(
            model_name="employeerecordupdatenotification",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "NEW")), fields=("employee_record",), name="unique_new_employee_record"
            ),
        ),
        migrations.AddConstraint(
            model_name="employeerecord",
            constraint=models.UniqueConstraint(
                fields=("asp_measure", "siret", "approval_number"), name="unique_asp_measure_siret_approval_number"
            ),
        ),
    ]
