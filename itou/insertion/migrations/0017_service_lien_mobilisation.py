from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("insertion", "0016_service_volume_horaire_nombre_semaines"),
    ]

    operations = [
        migrations.AddField(
            model_name="service",
            name="lien_mobilisation",
            field=models.URLField(blank=True, max_length=2000, verbose_name="lien de mobilisation"),
        ),
    ]
