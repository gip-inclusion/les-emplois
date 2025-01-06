from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0017_add_hijack_permission"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="jobseekerprofile",
            name="ata_allocation_since",
        ),
    ]
