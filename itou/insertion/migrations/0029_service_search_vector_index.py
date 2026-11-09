import django.contrib.postgres.indexes
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("insertion", "0028_service_search_vector"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="service",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["search_vector"], name="insertion_s_search__8b8029_gin"
            ),
        ),
    ]
