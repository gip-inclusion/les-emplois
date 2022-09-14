import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="FileScanReport",
            options={"verbose_name": "rapport d’analyse", "verbose_name_plural": "rapports d’analyse"},
            fields=[
                ("key", models.CharField(max_length=1024, primary_key=True, serialize=False)),
                ("signature", models.CharField(max_length=255)),
                ("reported_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("virus", models.BooleanField(null=True, verbose_name="fichier infecté")),
                ("comment", models.TextField(blank=True, verbose_name="commentaire")),
            ],
        ),
    ]
