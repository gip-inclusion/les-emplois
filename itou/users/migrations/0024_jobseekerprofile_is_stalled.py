from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("asp", "0005_remove_commune_aps_communes_name_gin_trgm_and_more"),
        ("prescribers", "0009_deactivate_inactive_users_memberships"),
        ("users", "0023_jobseekerprofile_created_by_prescriber_organization"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobseekerprofile",
            name="is_stalled",
            field=models.BooleanField(
                default=False,
                editable=False,
                help_text="Un candidat est dans la file active de l'IAE depuis plus de 30 jours s'il a émis une candidature dans les 6 derniers mois, n'a pas de candidature acceptée, et a émis sa première candidature il y a plus de 30 jours.",  # noqa: E501
                verbose_name="candidat sans solution",
            ),
        ),
        migrations.AddIndex(
            model_name="jobseekerprofile",
            index=models.Index(
                condition=models.Q(("is_stalled", True)), fields=["is_stalled"], name="users_jobseeker_stalled_idx"
            ),
        ),
    ]
