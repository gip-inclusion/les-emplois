import django.db.models.functions.datetime
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0008_poleemploiapproval_nir_idx"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="suspension",
            constraint=models.CheckConstraint(
                check=models.Q(
                    (
                        "start_at__lte",
                        django.db.models.functions.datetime.TruncDate(django.db.models.functions.datetime.Now()),
                    )
                ),
                name="suspension_cannot_start_in_the_future",
            ),
        ),
    ]
