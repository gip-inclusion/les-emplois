from django.conf import settings
from django.db import migrations, models

import itou.institutions.enums


class Migration(migrations.Migration):
    dependencies = [
        ("cities", "0002_city_last_synced_at"),
        ("institutions", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="institution",
            constraint=models.UniqueConstraint(
                condition=models.Q(("kind__in", itou.institutions.enums.InstitutionKind.get_singletons())),
                fields=("kind",),
                name="unique_national_institutions",
            ),
        ),
    ]
