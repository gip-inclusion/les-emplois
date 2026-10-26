from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("insertion", "0022_remove_service_contact_is_public"),
    ]

    operations = [
        migrations.AddField(
            model_name="service",
            name="score_qualite",
            field=models.FloatField(default=0, verbose_name="score de qualité data·inclusion"),
            preserve_default=False,
        ),
    ]
