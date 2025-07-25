# Generated by Django 5.2.4 on 2025-07-21 14:29

import uuid

from django.db import migrations, models

import itou.archive.models


class Migration(migrations.Migration):
    dependencies = [
        ("archive", "0010_alter_anonymizedapplication_options_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="AnonymizedApproval",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "anonymized_at",
                    models.DateField(
                        default=itou.archive.models.current_year_month,
                        editable=False,
                        verbose_name="anonymisé en année-mois",
                    ),
                ),
                ("origin", models.CharField(verbose_name="origine du PASS")),
                (
                    "origin_company_kind",
                    models.CharField(
                        blank=True,
                        null=True,
                        verbose_name="type d'entreprise à l'origine du PASS",
                    ),
                ),
                (
                    "origin_sender_kind",
                    models.CharField(
                        blank=True,
                        null=True,
                        verbose_name="type d'emetteur de la candidature à l'origine du PASS",
                    ),
                ),
                (
                    "origin_prescriber_organization_kind",
                    models.CharField(
                        blank=True,
                        null=True,
                        verbose_name="typologie du prescripteur à l'origine du PASS",
                    ),
                ),
                (
                    "start_at",
                    models.DateField(
                        blank=True,
                        null=True,
                        verbose_name="année et mois de début du PASS",
                    ),
                ),
                (
                    "end_at",
                    models.DateField(
                        blank=True,
                        null=True,
                        verbose_name="année et mois de fin du PASS",
                    ),
                ),
                (
                    "had_eligibility_diagnosis",
                    models.BooleanField(default=False, verbose_name="a eu un diagnostic d'éligibilité"),
                ),
                (
                    "number_of_prolongations",
                    models.PositiveIntegerField(default=0, verbose_name="nombre de prolongations"),
                ),
                (
                    "duration_of_prolongations",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="durée totale des prolongations en jours",
                    ),
                ),
                (
                    "number_of_suspensions",
                    models.PositiveIntegerField(default=0, verbose_name="nombre de suspensions"),
                ),
                (
                    "duration_of_suspensions",
                    models.PositiveIntegerField(default=0, verbose_name="durée totale des suspensions en jours"),
                ),
                (
                    "number_of_job_applications",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="nombre de candidatures pour lesquelles le PASS a été utilisé",
                    ),
                ),
                (
                    "number_of_accepted_job_applications",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="nombre de candidatures acceptées pour lesquelles le PASS a été utilisé",
                    ),
                ),
            ],
            options={
                "verbose_name": "PASS IAE anonymisé",
                "verbose_name_plural": "PASS IAE anonymisés",
                "ordering": ["-anonymized_at", "-start_at"],
            },
        ),
        migrations.CreateModel(
            name="AnonymizedGEIQEligibilityDiagnosis",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "anonymized_at",
                    models.DateField(
                        default=itou.archive.models.current_year_month,
                        editable=False,
                        verbose_name="anonymisé en année-mois",
                    ),
                ),
                (
                    "created_at",
                    models.DateField(verbose_name="année et mois de création du diagnostic"),
                ),
                (
                    "expired_at",
                    models.DateField(
                        blank=True,
                        null=True,
                        verbose_name="année et mois d'expiration du diagnostic",
                    ),
                ),
                (
                    "job_seeker_birth_year",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        null=True,
                        verbose_name="année de naissance du candidat",
                    ),
                ),
                (
                    "job_seeker_department",
                    models.CharField(
                        blank=True,
                        max_length=3,
                        null=True,
                        verbose_name="département du candidat",
                    ),
                ),
                (
                    "author_kind",
                    models.CharField(verbose_name="type de l'auteur du diagnostic"),
                ),
                (
                    "author_prescriber_organization_kind",
                    models.CharField(
                        blank=True,
                        null=True,
                        verbose_name="type de l'organisation prescriptrice de l'auteur du diagnostic",
                    ),
                ),
                (
                    "number_of_administrative_criteria",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="nombre de critères administratifs selectionnés",
                    ),
                ),
                (
                    "number_of_administrative_criteria_level_1",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="nombre de critères administratifs de niveau 1",
                    ),
                ),
                (
                    "number_of_administrative_criteria_level_2",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="nombre de critères administratifs de niveau 2",
                    ),
                ),
                (
                    "number_of_certified_administrative_criteria",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="nombre de critères administratifs certifiés",
                    ),
                ),
                (
                    "selected_administrative_criteria",
                    models.JSONField(
                        default=list,
                        verbose_name="critères administratifs sélectionnés",
                    ),
                ),
                (
                    "number_of_job_applications",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="nombre de candidatures pour lesquelles le diagnostic a été utilisé",
                    ),
                ),
                (
                    "number_of_accepted_job_applications",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="nombre de candidatures acceptées pour lesquelles le diagnostic a été utilisé",
                    ),
                ),
            ],
            options={
                "verbose_name": "diagnostic d'éligibilité GEIQ anonymisé",
                "verbose_name_plural": "diagnostics d'éligibilité GEIQ anonymisés",
                "ordering": ["-anonymized_at", "-created_at"],
            },
        ),
        migrations.CreateModel(
            name="AnonymizedSIAEEligibilityDiagnosis",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "anonymized_at",
                    models.DateField(
                        default=itou.archive.models.current_year_month,
                        editable=False,
                        verbose_name="anonymisé en année-mois",
                    ),
                ),
                (
                    "created_at",
                    models.DateField(verbose_name="année et mois de création du diagnostic"),
                ),
                (
                    "expired_at",
                    models.DateField(
                        blank=True,
                        null=True,
                        verbose_name="année et mois d'expiration du diagnostic",
                    ),
                ),
                (
                    "job_seeker_birth_year",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        null=True,
                        verbose_name="année de naissance du candidat",
                    ),
                ),
                (
                    "job_seeker_department",
                    models.CharField(
                        blank=True,
                        max_length=3,
                        null=True,
                        verbose_name="département du candidat",
                    ),
                ),
                (
                    "author_kind",
                    models.CharField(verbose_name="type de l'auteur du diagnostic"),
                ),
                (
                    "author_prescriber_organization_kind",
                    models.CharField(
                        blank=True,
                        null=True,
                        verbose_name="type de l'organisation prescriptrice de l'auteur du diagnostic",
                    ),
                ),
                (
                    "number_of_administrative_criteria",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="nombre de critères administratifs selectionnés",
                    ),
                ),
                (
                    "number_of_administrative_criteria_level_1",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="nombre de critères administratifs de niveau 1",
                    ),
                ),
                (
                    "number_of_administrative_criteria_level_2",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="nombre de critères administratifs de niveau 2",
                    ),
                ),
                (
                    "number_of_certified_administrative_criteria",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="nombre de critères administratifs certifiés",
                    ),
                ),
                (
                    "selected_administrative_criteria",
                    models.JSONField(
                        default=list,
                        verbose_name="critères administratifs sélectionnés",
                    ),
                ),
                (
                    "number_of_job_applications",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="nombre de candidatures pour lesquelles le diagnostic a été utilisé",
                    ),
                ),
                (
                    "number_of_accepted_job_applications",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="nombre de candidatures acceptées pour lesquelles le diagnostic a été utilisé",
                    ),
                ),
                (
                    "author_siae_kind",
                    models.CharField(
                        blank=True,
                        null=True,
                        verbose_name="type de SIAE de l'auteur du diagnostic",
                    ),
                ),
                (
                    "number_of_approvals",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="nombre de PASS IAE accordés suite au diagnostic",
                    ),
                ),
                (
                    "first_approval_start_at",
                    models.DateField(
                        blank=True,
                        null=True,
                        verbose_name="année et mois de début du premier PASS IAE accordé suite au diagnostic",
                    ),
                ),
                (
                    "last_approval_end_at",
                    models.DateField(
                        blank=True,
                        null=True,
                        verbose_name="année et mois de fin du dernier PASS IAE accordé suite au diagnostic",
                    ),
                ),
            ],
            options={
                "verbose_name": "diagnostic d'éligibilité SIAE anonymisé",
                "verbose_name_plural": "diagnostics d'éligibilité SIAE anonymisés",
                "ordering": ["-anonymized_at", "-created_at"],
            },
        ),
        migrations.AddField(
            model_name="anonymizedapplication",
            name="had_approval",
            field=models.BooleanField(default=False, verbose_name="avait un PASS IAE"),
        ),
        migrations.AddField(
            model_name="anonymizedjobseeker",
            name="count_approvals",
            field=models.PositiveIntegerField(default=0, verbose_name="nombre de PASS IAE accordés"),
        ),
        migrations.AddField(
            model_name="anonymizedjobseeker",
            name="count_eligibility_diagnoses",
            field=models.PositiveIntegerField(default=0, verbose_name="nombre de diagnostics d'éligibilité"),
        ),
        migrations.AddField(
            model_name="anonymizedjobseeker",
            name="first_approval_start_at",
            field=models.DateField(
                blank=True,
                null=True,
                verbose_name="année et mois de début du premier PASS IAE accordé",
            ),
        ),
        migrations.AddField(
            model_name="anonymizedjobseeker",
            name="last_approval_end_at",
            field=models.DateField(
                blank=True,
                null=True,
                verbose_name="année et mois de fin du dernier PASS IAE accordé",
            ),
        ),
    ]
