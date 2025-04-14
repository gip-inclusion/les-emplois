from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("antivirus", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="scan",
            name="clamav_completed_at",
            field=models.DateTimeField(db_index=True, null=True, verbose_name="analyse ClamAV le"),
        ),
    ]
