from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("insertion", "0017_remove_orientation_attachments_alter_orientation_id"),
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
        migrations.AddField(
            model_name="service",
            name="nombre_semaines",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="nombre de semaines"),
        ),
        migrations.AddField(
            model_name="service",
            name="volume_horaire_hebdomadaire",
            field=models.FloatField(blank=True, null=True, verbose_name="volume horaire hebdomadaire"),
        ),
        migrations.AddField(
            model_name="service",
            name="lien_mobilisation",
            field=models.URLField(blank=True, max_length=2000, verbose_name="lien de mobilisation"),
        ),
        migrations.AddField(
            model_name="structure",
            name="accessibilite_lieu",
            field=models.URLField(blank=True, max_length=2000, verbose_name="accessibilité du lieu"),
        ),
    ]
