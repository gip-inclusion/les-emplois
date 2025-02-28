# Generated by Django 5.1.5 on 2025-02-11 21:41

import django.db.models.functions.text
from django.db import migrations, models

import itou.utils.models


class Migration(migrations.Migration):
    dependencies = [
        ("cities", "0001_initial"),
        ("utils", "0002_slyly_immutable_unaccent"),
    ]

    operations = [
        migrations.AddField(
            model_name="city",
            name="normalized_name",
            field=models.GeneratedField(
                db_persist=True,
                expression=django.db.models.functions.text.Replace(
                    django.db.models.functions.text.Lower(itou.utils.models.SlylyImmutableUnaccent("name")),
                    models.Value("-"),
                    models.Value(" "),
                ),
                output_field=models.CharField(),
                verbose_name="nom normalisé pour faciliter la recherche",
            ),
        ),
    ]
