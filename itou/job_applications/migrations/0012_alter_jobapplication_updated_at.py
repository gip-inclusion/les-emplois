from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("job_applications", "0011_added_geiq_qualification_and_training_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="jobapplication",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, db_index=True, null=True, verbose_name="Date de modification"),
        ),
    ]
