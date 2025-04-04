# Generated by Django 5.1.4 on 2025-01-10 14:38

import django.contrib.postgres.lookups
import django.contrib.postgres.search
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0020_add_simple_unaccent_search_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="full_name_search_vector",
            field=models.GeneratedField(
                db_persist=True,
                expression=django.contrib.postgres.search.SearchVector(
                    "first_name", "last_name", config="simple_unaccent"
                ),
                output_field=django.contrib.postgres.search.SearchVectorField(),
                verbose_name="nom complet utilisé pour rechercher un utilisateur",
            ),
        ),
    ]
