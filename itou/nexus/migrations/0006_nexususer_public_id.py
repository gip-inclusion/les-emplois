import uuid

import django.contrib.postgres.functions
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("nexus", "0005_remove_activatedservice_user_service_unique_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="nexususer",
            name="public_id",
            field=models.UUIDField(
                db_default=django.contrib.postgres.functions.RandomUUID(),
                default=uuid.uuid4,
                help_text="identifiant opaque, pour les API et les URLs publiques",
                unique=True,
                verbose_name="identifiant public",
            ),
        ),
    ]
