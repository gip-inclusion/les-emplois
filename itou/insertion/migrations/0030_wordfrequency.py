import django.contrib.postgres.indexes
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("insertion", "0029_service_search_vector_index"),
    ]

    operations = [
        migrations.CreateModel(
            name="WordFrequency",
            fields=[
                ("stem", models.CharField(primary_key=True, serialize=False, verbose_name="radical")),
                ("service_count", models.PositiveIntegerField(verbose_name="nombre de services contenant le mot")),
            ],
            options={
                "verbose_name": "fréquence d'apparition d'un mot dans les services et structures",
                "indexes": [
                    django.contrib.postgres.indexes.GinIndex(
                        fields=["stem"], name="wordfrequency_stem_gin", opclasses=["gin_trgm_ops"]
                    )
                ],
            },
        ),
    ]
