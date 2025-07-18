# Generated by Django 5.0.3 on 2024-03-22 12:11

import uuid

import django.contrib.gis.db.models.fields
import django.core.serializers.json
import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import itou.utils.validators


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("cities", "0001_initial"),
        ("jobs", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Siae",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("address_line_1", models.CharField(blank=True, max_length=255, verbose_name="adresse")),
                (
                    "address_line_2",
                    models.CharField(
                        blank=True,
                        help_text="Appartement, suite, bloc, bâtiment, boite postale, etc.",
                        max_length=255,
                        verbose_name="complément d'adresse",
                    ),
                ),
                (
                    "post_code",
                    models.CharField(
                        blank=True,
                        max_length=5,
                        validators=[itou.utils.validators.validate_post_code],
                        verbose_name="code postal",
                    ),
                ),
                ("city", models.CharField(blank=True, max_length=255, verbose_name="ville")),
                (
                    "department",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("01", "01 - Ain"),
                            ("02", "02 - Aisne"),
                            ("03", "03 - Allier"),
                            ("04", "04 - Alpes-de-Haute-Provence"),
                            ("05", "05 - Hautes-Alpes"),
                            ("06", "06 - Alpes-Maritimes"),
                            ("07", "07 - Ardèche"),
                            ("08", "08 - Ardennes"),
                            ("09", "09 - Ariège"),
                            ("10", "10 - Aube"),
                            ("11", "11 - Aude"),
                            ("12", "12 - Aveyron"),
                            ("13", "13 - Bouches-du-Rhône"),
                            ("14", "14 - Calvados"),
                            ("15", "15 - Cantal"),
                            ("16", "16 - Charente"),
                            ("17", "17 - Charente-Maritime"),
                            ("18", "18 - Cher"),
                            ("19", "19 - Corrèze"),
                            ("2A", "2A - Corse-du-Sud"),
                            ("2B", "2B - Haute-Corse"),
                            ("21", "21 - Côte-d'Or"),
                            ("22", "22 - Côtes-d'Armor"),
                            ("23", "23 - Creuse"),
                            ("24", "24 - Dordogne"),
                            ("25", "25 - Doubs"),
                            ("26", "26 - Drôme"),
                            ("27", "27 - Eure"),
                            ("28", "28 - Eure-et-Loir"),
                            ("29", "29 - Finistère"),
                            ("30", "30 - Gard"),
                            ("31", "31 - Haute-Garonne"),
                            ("32", "32 - Gers"),
                            ("33", "33 - Gironde"),
                            ("34", "34 - Hérault"),
                            ("35", "35 - Ille-et-Vilaine"),
                            ("36", "36 - Indre"),
                            ("37", "37 - Indre-et-Loire"),
                            ("38", "38 - Isère"),
                            ("39", "39 - Jura"),
                            ("40", "40 - Landes"),
                            ("41", "41 - Loir-et-Cher"),
                            ("42", "42 - Loire"),
                            ("43", "43 - Haute-Loire"),
                            ("44", "44 - Loire-Atlantique"),
                            ("45", "45 - Loiret"),
                            ("46", "46 - Lot"),
                            ("47", "47 - Lot-et-Garonne"),
                            ("48", "48 - Lozère"),
                            ("49", "49 - Maine-et-Loire"),
                            ("50", "50 - Manche"),
                            ("51", "51 - Marne"),
                            ("52", "52 - Haute-Marne"),
                            ("53", "53 - Mayenne"),
                            ("54", "54 - Meurthe-et-Moselle"),
                            ("55", "55 - Meuse"),
                            ("56", "56 - Morbihan"),
                            ("57", "57 - Moselle"),
                            ("58", "58 - Nièvre"),
                            ("59", "59 - Nord"),
                            ("60", "60 - Oise"),
                            ("61", "61 - Orne"),
                            ("62", "62 - Pas-de-Calais"),
                            ("63", "63 - Puy-de-Dôme"),
                            ("64", "64 - Pyrénées-Atlantiques"),
                            ("65", "65 - Hautes-Pyrénées"),
                            ("66", "66 - Pyrénées-Orientales"),
                            ("67", "67 - Bas-Rhin"),
                            ("68", "68 - Haut-Rhin"),
                            ("69", "69 - Rhône"),
                            ("70", "70 - Haute-Saône"),
                            ("71", "71 - Saône-et-Loire"),
                            ("72", "72 - Sarthe"),
                            ("73", "73 - Savoie"),
                            ("74", "74 - Haute-Savoie"),
                            ("75", "75 - Paris"),
                            ("76", "76 - Seine-Maritime"),
                            ("77", "77 - Seine-et-Marne"),
                            ("78", "78 - Yvelines"),
                            ("79", "79 - Deux-Sèvres"),
                            ("80", "80 - Somme"),
                            ("81", "81 - Tarn"),
                            ("82", "82 - Tarn-et-Garonne"),
                            ("83", "83 - Var"),
                            ("84", "84 - Vaucluse"),
                            ("85", "85 - Vendée"),
                            ("86", "86 - Vienne"),
                            ("87", "87 - Haute-Vienne"),
                            ("88", "88 - Vosges"),
                            ("89", "89 - Yonne"),
                            ("90", "90 - Territoire de Belfort"),
                            ("91", "91 - Essonne"),
                            ("92", "92 - Hauts-de-Seine"),
                            ("93", "93 - Seine-Saint-Denis"),
                            ("94", "94 - Val-de-Marne"),
                            ("95", "95 - Val-d'Oise"),
                            ("971", "971 - Guadeloupe"),
                            ("972", "972 - Martinique"),
                            ("973", "973 - Guyane"),
                            ("974", "974 - La Réunion"),
                            ("975", "975 - Saint-Pierre-et-Miquelon"),
                            ("976", "976 - Mayotte"),
                            ("977", "977 - Saint-Barthélémy"),
                            ("978", "978 - Saint-Martin"),
                            ("984", "984 - Terres australes et antarctiques françaises"),
                            ("986", "986 - Wallis-et-Futuna"),
                            ("987", "987 - Polynésie française"),
                            ("988", "988 - Nouvelle-Calédonie"),
                            ("989", "989 - Île Clipperton"),
                        ],
                        db_index=True,
                        max_length=3,
                        verbose_name="département",
                    ),
                ),
                (
                    "coords",
                    django.contrib.gis.db.models.fields.PointField(blank=True, geography=True, null=True, srid=4326),
                ),
                ("geocoding_score", models.FloatField(blank=True, null=True, verbose_name="score du geocoding")),
                (
                    "siret",
                    models.CharField(
                        db_index=True,
                        max_length=14,
                        validators=[itou.utils.validators.validate_siret],
                        verbose_name="siret",
                    ),
                ),
                (
                    "naf",
                    models.CharField(
                        blank=True, max_length=5, validators=[itou.utils.validators.validate_naf], verbose_name="naf"
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("ACI", "Atelier chantier d'insertion"),
                            ("AI", "Association intermédiaire"),
                            ("EA", "Entreprise adaptée"),
                            ("EATT", "Entreprise adaptée de travail temporaire"),
                            ("EI", "Entreprise d'insertion"),
                            ("EITI", "Entreprise d'insertion par le travail indépendant"),
                            ("ETTI", "Entreprise de travail temporaire d'insertion"),
                            ("GEIQ", "Groupement d'employeurs pour l'insertion et la qualification"),
                            ("OPCS", "Organisation porteuse de la clause sociale"),
                        ],
                        default="EI",
                        max_length=8,
                        verbose_name="type",
                    ),
                ),
                ("name", models.CharField(max_length=255, verbose_name="nom")),
                ("brand", models.CharField(blank=True, max_length=255, verbose_name="enseigne")),
                ("phone", models.CharField(blank=True, max_length=20, verbose_name="téléphone")),
                ("email", models.EmailField(blank=True, max_length=254, verbose_name="e-mail")),
                ("website", models.URLField(blank=True, verbose_name="site web")),
                ("description", models.TextField(blank=True, verbose_name="description")),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now, verbose_name="date de création"),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_siae_set",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="créé par",
                    ),
                ),
                ("updated_at", models.DateTimeField(blank=True, null=True, verbose_name="date de modification")),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("ASP", "Export ASP"),
                            ("GEIQ", "Export GEIQ"),
                            ("EA_EATT", "Export EA+EATT"),
                            ("USER_CREATED", "Utilisateur (Antenne)"),
                            ("STAFF_CREATED", "Staff Itou"),
                        ],
                        default="ASP",
                        max_length=20,
                        verbose_name="source de données",
                    ),
                ),
                ("provided_support", models.TextField(blank=True, verbose_name="type d'accompagnement")),
                (
                    "auth_email",
                    models.EmailField(blank=True, max_length=254, verbose_name="e-mail d'authentification"),
                ),
                (
                    "block_job_applications",
                    models.BooleanField(default=False, verbose_name="blocage des candidatures"),
                ),
                (
                    "job_applications_blocked_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="date du dernier blocage de candidatures"
                    ),
                ),
                ("uid", models.UUIDField(db_index=True, default=uuid.uuid4, unique=True)),
                (
                    "job_app_score",
                    models.FloatField(
                        null=True,
                        verbose_name="score de recommandation (ratio de candidatures récentes vs nombre d'offres "
                        "d'emploi)",
                    ),
                ),
            ],
            options={
                "verbose_name": "entreprise",
                "unique_together": {("siret", "kind")},
                "db_table": "siaes_siae",
            },
        ),
        migrations.CreateModel(
            name="SiaeMembership",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("joined_at", models.DateTimeField(default=django.utils.timezone.now, verbose_name="date d'adhésion")),
                ("is_admin", models.BooleanField(default=False, verbose_name="administrateur")),
                ("siae", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="companies.siae")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ("notifications", models.JSONField(blank=True, default=dict, verbose_name="notifications")),
                ("is_active", models.BooleanField(default=True, verbose_name="rattachement actif")),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now, verbose_name="date de création"),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="date de modification")),
                (
                    "updated_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="updated_siaemembership_set",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="mis à jour par",
                    ),
                ),
            ],
            options={
                "db_table": "siaes_siaemembership",
            },
        ),
        migrations.AddField(
            model_name="siae",
            name="members",
            field=models.ManyToManyField(
                blank=True, through="companies.SiaeMembership", to=settings.AUTH_USER_MODEL, verbose_name="membres"
            ),
        ),
        migrations.CreateModel(
            name="SiaeJobDescription",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now, verbose_name="date de création"),
                ),
                ("is_active", models.BooleanField(default=True, verbose_name="recrutement ouvert")),
                ("custom_name", models.CharField(blank=True, max_length=255, verbose_name="nom personnalisé")),
                ("description", models.TextField(blank=True, verbose_name="description")),
                ("ui_rank", models.PositiveSmallIntegerField(default=32767)),
                ("appellation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="jobs.appellation")),
                (
                    "siae",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="job_description_through",
                        to="companies.siae",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, db_index=True, verbose_name="date de modification"),
                ),
                (
                    "source_id",
                    models.CharField(
                        blank=True, max_length=255, null=True, verbose_name="ID dans le référentiel source"
                    ),
                ),
                (
                    "source_kind",
                    models.CharField(
                        choices=[("PE_API", "API France Travail")],
                        max_length=30,
                        null=True,
                        verbose_name="source de la donnée",
                    ),
                ),
                (
                    "contract_type",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("PERMANENT", "CDI"),
                            ("PERMANENT_I", "CDI inclusion"),
                            ("FIXED_TERM", "CDD"),
                            ("FIXED_TERM_USAGE", "CDD d'usage"),
                            ("FIXED_TERM_I", "CDD insertion"),
                            ("FIXED_TERM_I_PHC", "CDD-I PHC"),
                            ("FIXED_TERM_I_CVG", "CDD-I CVG"),
                            ("FIXED_TERM_TREMPLIN", "CDD Tremplin"),
                            ("APPRENTICESHIP", "Contrat d'apprentissage"),
                            ("PROFESSIONAL_TRAINING", "Contrat de professionalisation"),
                            ("TEMPORARY", "Contrat de mission intérimaire"),
                            ("BUSINESS_CREATION", "Accompagnement à la création d'entreprise"),
                            ("OTHER", "Autre type de contrat"),
                        ],
                        max_length=30,
                        verbose_name="type de contrat",
                    ),
                ),
                (
                    "hours_per_week",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        null=True,
                        validators=[django.core.validators.MaxValueValidator(48)],
                        verbose_name="nombre d'heures par semaine",
                    ),
                ),
                (
                    "is_qpv_mandatory",
                    models.BooleanField(default=False, verbose_name="une clause QPV est nécessaire pour ce poste"),
                ),
                (
                    "is_resume_mandatory",
                    models.BooleanField(default=False, verbose_name="CV nécessaire pour la candidature"),
                ),
                ("market_context_description", models.TextField(blank=True, verbose_name="contexte du marché")),
                (
                    "open_positions",
                    models.PositiveSmallIntegerField(blank=True, default=1, verbose_name="nombre de postes ouverts"),
                ),
                (
                    "other_contract_type",
                    models.CharField(blank=True, max_length=255, null=True, verbose_name="autre type de contrat"),
                ),
                ("profile_description", models.TextField(blank=True, verbose_name="profil recherché et pré-requis")),
                (
                    "location",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="cities.city",
                        verbose_name="localisation du poste",
                    ),
                ),
                (
                    "source_url",
                    models.URLField(blank=True, max_length=512, null=True, verbose_name="URL source de l'offre"),
                ),
                (
                    "contract_nature",
                    models.CharField(
                        blank=True,
                        choices=[("PEC_OFFER", "Contrat PEC - Parcours Emploi Compétences")],
                        max_length=64,
                        null=True,
                        verbose_name="nature du contrat",
                    ),
                ),
                (
                    "field_history",
                    models.JSONField(
                        default=list,
                        encoder=django.core.serializers.json.DjangoJSONEncoder,
                        null=True,
                        verbose_name="historique des champs modifiés sur le modèle",
                    ),
                ),
                (
                    "creation_source",
                    models.CharField(
                        choices=[
                            ("MANUALLY", "Fiche de poste créée manuellement"),
                            ("HIRING", "Fiche de poste créée automatiquement à l'embauche"),
                        ],
                        default="MANUALLY",
                        verbose_name="source de création de la fiche de poste",
                    ),
                ),
            ],
            options={
                "ordering": ["appellation__name", "ui_rank"],
                "verbose_name": "fiche de poste",
                "verbose_name_plural": "fiches de postes",
                "unique_together": set(),
                "db_table": "siaes_siaejobdescription",
            },
        ),
        migrations.CreateModel(
            name="SiaeConvention",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("ACI", "Atelier chantier d'insertion"),
                            ("AI", "Association intermédiaire"),
                            ("EI", "Entreprise d'insertion"),
                            ("EITI", "Entreprise d'insertion par le travail indépendant"),
                            ("ETTI", "Entreprise de travail temporaire d'insertion"),
                        ],
                        default="EI",
                        max_length=4,
                        verbose_name="type",
                    ),
                ),
                (
                    "siret_signature",
                    models.CharField(
                        db_index=True,
                        max_length=14,
                        validators=[itou.utils.validators.validate_siret],
                        verbose_name="siret à la signature",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        db_index=True,
                        default=True,
                        help_text="Précise si la convention est active c.a.d. si elle a au moins une annexe "
                        "financière valide à ce jour.",
                        verbose_name="active",
                    ),
                ),
                (
                    "deactivated_at",
                    models.DateTimeField(
                        blank=True,
                        db_index=True,
                        null=True,
                        verbose_name="date de désactivation et début de délai de grâce",
                    ),
                ),
                (
                    "reactivated_at",
                    models.DateTimeField(blank=True, null=True, verbose_name="date de réactivation manuelle"),
                ),
                ("asp_id", models.IntegerField(db_index=True, verbose_name="ID ASP de la SIAE")),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now, verbose_name="date de création"),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="date de modification")),
                (
                    "reactivated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="reactivated_siae_convention_set",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="réactivée manuellement par",
                    ),
                ),
            ],
            options={
                "verbose_name": "convention",
                "unique_together": {("asp_id", "kind")},
                "db_table": "siaes_siaeconvention",
            },
        ),
        migrations.AddField(
            model_name="siae",
            name="convention",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.RESTRICT,
                related_name="siaes",
                to="companies.siaeconvention",
            ),
        ),
        migrations.AddField(
            model_name="siae",
            name="ban_api_resolved_address",
            field=models.TextField(
                blank=True, null=True, verbose_name="libellé d'adresse retourné par le dernier geocoding"
            ),
        ),
        migrations.AddField(
            model_name="siae",
            name="geocoding_updated_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="dernière modification du geocoding"),
        ),
        migrations.AddField(
            model_name="siae",
            name="jobs",
            field=models.ManyToManyField(
                blank=True, through="companies.SiaeJobDescription", to="jobs.appellation", verbose_name="métiers"
            ),
        ),
        migrations.AlterField(
            model_name="siae",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, verbose_name="date de modification"),
        ),
        migrations.CreateModel(
            name="SiaeFinancialAnnex",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "number",
                    models.CharField(
                        db_index=True,
                        max_length=17,
                        unique=True,
                        validators=[itou.utils.validators.validate_af_number],
                        verbose_name="numéro d'annexe financière",
                    ),
                ),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("VALIDE", "Validée"),
                            ("PROVISOIRE", "Provisoire (valide)"),
                            ("HISTORISE", "Archivée (invalide)"),
                            ("ANNULE", "Annulée"),
                            ("SAISI", "Saisie (invalide)"),
                            ("BROUILLON", "Brouillon (invalide)"),
                            ("CLOTURE", "Cloturée (invalide)"),
                            ("REJETE", "Rejetée"),
                        ],
                        max_length=20,
                        verbose_name="état",
                    ),
                ),
                ("start_at", models.DateTimeField(verbose_name="date de début d'effet")),
                ("end_at", models.DateTimeField(verbose_name="date de fin d'effet")),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now, verbose_name="date de création"),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="date de modification")),
                (
                    "convention",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="financial_annexes",
                        to="companies.siaeconvention",
                    ),
                ),
            ],
            options={
                "verbose_name": "annexe financière",
                "verbose_name_plural": "annexes financières",
                "db_table": "siaes_siaefinancialannex",
            },
        ),
        migrations.AlterModelTable(
            name="siae",
            table=None,
        ),
        migrations.AlterModelTable(
            name="siaeconvention",
            table=None,
        ),
        migrations.AlterModelTable(
            name="siaefinancialannex",
            table=None,
        ),
        migrations.AlterModelTable(
            name="siaejobdescription",
            table=None,
        ),
        migrations.AlterModelTable(
            name="siaemembership",
            table=None,
        ),
        migrations.RenameModel(
            old_name="Siae",
            new_name="Company",
        ),
        migrations.AlterField(
            model_name="siaejobdescription",
            name="siae",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="job_description_through",
                to="companies.company",
            ),
        ),
        migrations.AlterField(
            model_name="siaemembership",
            name="siae",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="companies.company"),
        ),
        migrations.AlterField(
            model_name="company",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="created_company_set",
                to=settings.AUTH_USER_MODEL,
                verbose_name="créé par",
            ),
        ),
        migrations.RenameModel(
            old_name="SiaeMembership",
            new_name="CompanyMembership",
        ),
        migrations.AlterField(
            model_name="company",
            name="members",
            field=models.ManyToManyField(
                blank=True,
                through="companies.CompanyMembership",
                through_fields=("company", "user"),
                to=settings.AUTH_USER_MODEL,
                verbose_name="membres",
            ),
        ),
        migrations.AlterField(
            model_name="companymembership",
            name="updated_by",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="updated_companymembership_set",
                to=settings.AUTH_USER_MODEL,
                verbose_name="mis à jour par",
            ),
        ),
        migrations.RenameModel(
            old_name="SiaeJobDescription",
            new_name="JobDescription",
        ),
        migrations.RenameField(
            model_name="jobdescription",
            old_name="siae",
            new_name="company",
        ),
        migrations.RenameField(
            model_name="companymembership",
            old_name="siae",
            new_name="company",
        ),
        migrations.AddField(
            model_name="company",
            name="insee_city",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="cities.city"
            ),
        ),
        migrations.AddConstraint(
            model_name="jobdescription",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("source_kind__isnull", False),
                    ("source_id__isnull", False),
                    models.Q(("source_id", ""), _negated=True),
                ),
                fields=("source_kind", "source_id"),
                name="source_id_kind_unique_without_null_values",
            ),
        ),
        migrations.AddConstraint(
            model_name="companymembership",
            constraint=models.UniqueConstraint(fields=("user", "company"), name="user_company_unique"),
        ),
    ]
