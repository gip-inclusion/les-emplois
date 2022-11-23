import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("files", "0001_initial"),
        ("antivirus", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Scan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("clamav_signature", models.TextField()),
                ("clamav_completed_at", models.DateTimeField(null=True, verbose_name="analyse ClamAV le")),
                ("clamav_infected", models.BooleanField(null=True, verbose_name="fichier infecté selon ClamAV")),
                ("comment", models.TextField(blank=True, verbose_name="commentaire")),
                ("file", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to="files.file")),
            ],
            options={
                "verbose_name": "analyse antivirus",
                "verbose_name_plural": "analyses antivirus",
            },
        ),
        migrations.DeleteModel(
            name="FileScanReport",
        ),
    ]
