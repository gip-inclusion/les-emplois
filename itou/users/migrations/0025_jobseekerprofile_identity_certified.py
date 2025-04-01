from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0024_jobseekerprofile_is_stalled"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobseekerprofile",
            name="identity_certified",
            field=models.BooleanField(editable=False, db_default=False),
        ),
    ]
