from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("job_applications", "0009_alter_jobapplication_state_prioraction"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobapplication",
            name="prehiring_guidance_days",
            field=models.PositiveSmallIntegerField(
                blank=True, null=True, verbose_name="nombre de jours d’accompagnement avant contrat"
            ),
        ),
    ]
