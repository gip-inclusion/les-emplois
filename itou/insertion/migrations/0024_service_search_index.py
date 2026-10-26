import django.contrib.postgres.indexes
import django.contrib.postgres.search
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("insertion", "0023_service_score_qualite"),
    ]

    operations = [
        migrations.CreateModel(
            name="SearchLexeme",
            fields=[
                ("word", models.CharField(primary_key=True, serialize=False, verbose_name="mot")),
                ("ndoc", models.PositiveIntegerField(verbose_name="nombre de services")),
            ],
            options={
                "verbose_name": "mot de l'index de recherche",
            },
        ),
        migrations.AddField(
            model_name="service",
            name="search_vector",
            field=django.contrib.postgres.search.SearchVectorField(null=True),
        ),
        migrations.AddIndex(
            model_name="service",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["search_vector"], name="insertion_s_search__8b8029_gin"
            ),
        ),
        migrations.AddIndex(
            model_name="searchlexeme",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["word"], name="searchlexeme_word_gin", opclasses=["gin_trgm_ops"]
            ),
        ),
    ]
