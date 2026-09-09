from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("insertion", "0014_orientationprocesslink"),
    ]

    operations = [
        migrations.AddField(
            model_name="service",
            name="extra",
            field=models.JSONField(
                null=True,
                verbose_name="données complémentaires (data·inclusion)",
            ),
        ),
    ]
