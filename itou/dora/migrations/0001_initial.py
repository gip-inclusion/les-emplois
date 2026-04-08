import django.contrib.gis.db.models.fields
import django.db.models.deletion
from django.db import migrations, models

import itou.utils.validators


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("cities", "0002_city_last_synced_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReferenceDatum",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("FEE", "Frais"),
                            ("RECEPTION", "Mode d'accueil"),
                            ("MOBILIZATION", "Mode de mobilisation"),
                            ("MOBILIZATION_PUBLIC", "Personne mobilisatrices"),
                            ("PUBLIC", "Public"),
                            ("NETWORK", "Réseau porteur"),
                            ("THEMATIC", "Thématique"),
                            ("SERVICE_KIND", "Type de service"),
                            ("SOURCE", "Source"),
                        ]
                    ),
                ),
                ("value", models.CharField(verbose_name="valeur")),
                ("label", models.CharField()),
                ("description", models.TextField(blank=True, null=True)),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("kind", "value"), name="unique_value_for_kind")],
            },
        ),
        migrations.CreateModel(
            name="Structure",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("address_line_1", models.CharField(blank=True, verbose_name="adresse")),
                (
                    "address_line_2",
                    models.CharField(
                        blank=True,
                        help_text="Appartement, suite, bloc, bâtiment, boite postale, etc.",
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
                ("city", models.CharField(blank=True, verbose_name="ville")),
                (
                    "coordinates",
                    django.contrib.gis.db.models.fields.PointField(blank=True, geography=True, null=True, srid=4326),
                ),
                ("uid", models.CharField(unique=True)),
                ("siret", models.CharField(blank=True)),
                ("name", models.CharField()),
                ("description", models.TextField(blank=True)),
                ("website", models.URLField(blank=True, max_length=512, verbose_name="site web")),
                ("email", models.EmailField(blank=True, max_length=254, verbose_name="e-mail")),
                ("phone", models.CharField(blank=True, max_length=20, verbose_name="téléphone")),
                ("updated_on", models.DateField()),
                (
                    "insee_city",
                    models.ForeignKey(null=True, on_delete=django.db.models.deletion.RESTRICT, to="cities.city"),
                ),
                (
                    "source",
                    models.ForeignKey(
                        limit_choices_to={"kind": "SOURCE"},
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="+",
                        to="dora.referencedatum",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="Service",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("address_line_1", models.CharField(blank=True, verbose_name="adresse")),
                (
                    "address_line_2",
                    models.CharField(
                        blank=True,
                        help_text="Appartement, suite, bloc, bâtiment, boite postale, etc.",
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
                ("city", models.CharField(blank=True, verbose_name="ville")),
                (
                    "coordinates",
                    django.contrib.gis.db.models.fields.PointField(blank=True, geography=True, null=True, srid=4326),
                ),
                ("uid", models.CharField(unique=True)),
                ("source_link", models.URLField(blank=True, max_length=512)),
                ("name", models.CharField()),
                ("description", models.TextField()),
                ("description_short", models.TextField(blank=True)),
                ("fee_details", models.TextField(blank=True)),
                ("publics_details", models.TextField(blank=True)),
                ("access_conditions", models.TextField(blank=True)),
                ("mobilizations_details", models.TextField(blank=True)),
                ("mobilization_link", models.URLField(blank=True, max_length=512)),
                ("opening_hours", models.CharField(blank=True, verbose_name="horaires d'accueil")),
                ("contact_full_name", models.CharField(blank=True)),
                ("contact_email", models.EmailField(blank=True, max_length=254, verbose_name="e-mail")),
                ("contact_phone", models.CharField(blank=True, max_length=20, verbose_name="téléphone")),
                ("is_orientable_with_form", models.BooleanField(default=True)),
                ("average_orientation_response_delay_days", models.PositiveIntegerField(null=True)),
                ("updated_on", models.DateField()),
                (
                    "fee",
                    models.ForeignKey(
                        limit_choices_to={"kind": "FEE"},
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="+",
                        to="dora.referencedatum",
                    ),
                ),
                (
                    "insee_city",
                    models.ForeignKey(null=True, on_delete=django.db.models.deletion.RESTRICT, to="cities.city"),
                ),
                (
                    "kind",
                    models.ForeignKey(
                        limit_choices_to={"kind": "SERVICE_KIND"},
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="+",
                        to="dora.referencedatum",
                    ),
                ),
                (
                    "mobilization_publics",
                    models.ManyToManyField(
                        limit_choices_to={"kind": "MOBILIZATION_PUBLIC"}, related_name="+", to="dora.referencedatum"
                    ),
                ),
                (
                    "mobilizations",
                    models.ManyToManyField(
                        limit_choices_to={"kind": "MOBILIZATION"}, related_name="+", to="dora.referencedatum"
                    ),
                ),
                (
                    "publics",
                    models.ManyToManyField(
                        limit_choices_to={"kind": "PUBLIC"}, related_name="+", to="dora.referencedatum"
                    ),
                ),
                (
                    "receptions",
                    models.ManyToManyField(
                        limit_choices_to={"kind": "RECEPTION"}, related_name="+", to="dora.referencedatum"
                    ),
                ),
                (
                    "source",
                    models.ForeignKey(
                        limit_choices_to={"kind": "SOURCE"},
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="+",
                        to="dora.referencedatum",
                    ),
                ),
                (
                    "thematics",
                    models.ManyToManyField(
                        limit_choices_to={"kind": "THEMATIC"}, related_name="+", to="dora.referencedatum"
                    ),
                ),
                ("structure", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="dora.structure")),
            ],
            options={
                "abstract": False,
            },
        ),
    ]
