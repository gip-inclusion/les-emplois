from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("status", "0001_initial"),
    ]

    operations = [
        migrations.DeleteModel(
            name="ProbeStatus",
        ),
    ]
