import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0002_rename_prolongationrequest_validated_by"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="prolongationrequest",
            name="assigned_to",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.RESTRICT,
                related_name="%(class)ss_assigned",
                to=settings.AUTH_USER_MODEL,
                verbose_name="prescripteur habilité qui a reçu la demande de prolongation",
            ),
        ),
    ]
