import django.contrib.postgres.search
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("insertion", "0027_service_score_qualite"),
    ]

    operations = [
        migrations.AddField(
            model_name="service",
            name="search_vector",
            field=django.contrib.postgres.search.SearchVectorField(null=True),
        ),
    ]
