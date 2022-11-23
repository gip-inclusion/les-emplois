import uuid

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Datum",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False)),
                ("code", models.TextField(choices=[])),
                ("bucket", models.TextField()),
                ("value", models.IntegerField()),
                ("measured_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                "verbose_name_plural": "Data",
            },
        ),
        migrations.AddIndex(
            model_name="datum",
            index=models.Index(fields=["measured_at", "code"], name="analytics_d_measure_a59c08_idx"),
        ),
        migrations.AlterUniqueTogether(
            name="datum",
            unique_together={("code", "bucket")},
        ),
    ]
