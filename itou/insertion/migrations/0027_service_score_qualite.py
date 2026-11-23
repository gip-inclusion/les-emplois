from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("insertion", "0026_remove_mobilizationevent_session_key_in_db"),
    ]

    operations = [
        migrations.AddField(
            model_name="service",
            name="score_qualite",
            field=models.FloatField(default=0, verbose_name="score de qualité data·inclusion"),
            preserve_default=False,
        ),
    ]
