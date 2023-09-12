from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("job_applications", "0014_jobapplication_inverted_vae_contract"),
    ]

    operations = [
        migrations.RunSQL(
            "UPDATE job_applications_jobapplication SET updated_at = created_at WHERE updated_at IS NULL;",
            reverse_sql=migrations.RunSQL.noop,
            elidable=True,
        ),
        migrations.AlterField(
            model_name="jobapplication",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, db_index=True, verbose_name="date de modification"),
        ),
    ]
