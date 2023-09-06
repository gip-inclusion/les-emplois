from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="File",
            fields=[
                ("key", models.CharField(max_length=1024, primary_key=True, serialize=False)),
                (
                    "last_modified",
                    models.DateTimeField(verbose_name="dernière modification sur Cellar", default=timezone.now),
                ),
            ],
            options={"verbose_name": "fichier"},
        ),
    ]
