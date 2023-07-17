from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0007_prolongation_report_file"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="poleemploiapproval",
            index=models.Index(fields=["nir"], name="nir_idx"),
        ),
    ]
