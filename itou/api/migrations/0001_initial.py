# Generated by Django 5.2.4 on 2025-07-15 09:40

import django.utils.timezone
from django.db import migrations, models

import itou.api.models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("companies", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="CompanyToken",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(default=itou.api.models._generate_key, unique=True)),
                (
                    "label",
                    models.CharField(
                        max_length=60, unique=True, verbose_name="mémo permettant d'identifier l'usage du jeton"
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("companies", models.ManyToManyField(related_name="api_tokens", to="companies.company")),
            ],
            options={
                "verbose_name": "jeton d'API entreprise",
                "verbose_name_plural": "jetons d'API entreprise",
            },
        ),
        migrations.CreateModel(
            name="DepartmentToken",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(default=itou.api.models._generate_key, unique=True)),
                (
                    "department",
                    models.CharField(
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
                        max_length=3,
                        verbose_name="département",
                    ),
                ),
                (
                    "label",
                    models.CharField(
                        max_length=60, unique=True, verbose_name="mémo permettant d'identifier l'usage du jeton"
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                "verbose_name": "jeton d'API département",
                "verbose_name_plural": "jetons d'API département",
            },
        ),
    ]
