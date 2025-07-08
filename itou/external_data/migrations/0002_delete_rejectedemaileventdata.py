from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("external_data", "0001_initial"),
    ]

    operations = [
        migrations.DeleteModel(
            name="RejectedEmailEventData",
        ),
    ]
