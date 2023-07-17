import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inclusion_connect", "0002_inclusionconnectstate_used_at_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="inclusionconnectstate",
            name="created_at",
            field=models.DateTimeField(
                db_index=True, default=django.utils.timezone.now, verbose_name="Date de création"
            ),
        ),
    ]
