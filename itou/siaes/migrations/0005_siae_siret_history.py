import django.contrib.postgres.fields
from django.db import migrations, models

import itou.utils.validators


class Migration(migrations.Migration):
    dependencies = [
        ("siaes", "0004_siaejobdescription_field_history"),
    ]

    operations = [
        migrations.AddField(
            model_name="siae",
            name="siret_history",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=14, validators=[itou.utils.validators.validate_siret]),
                default=list,
                size=None,
                verbose_name="historique des siret",
            ),
        ),
    ]
