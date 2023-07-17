from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("antivirus", "0002_scan_delete_filescanreport"),
    ]

    operations = [
        migrations.RenameField(
            model_name="scan",
            old_name="clamav_infected",
            new_name="infected",
        ),
    ]
