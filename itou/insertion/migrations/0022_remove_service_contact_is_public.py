from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("insertion", "0021_remove_dora_service_fields"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="service",
            name="contact_is_public",
        ),
    ]
