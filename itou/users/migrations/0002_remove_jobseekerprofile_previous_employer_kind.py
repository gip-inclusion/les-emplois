from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.RemoveField(model_name="jobseekerprofile", name="previous_employer_kind")],
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE users_jobseekerprofile ALTER COLUMN previous_employer_kind SET DEFAULT ''"
                )
            ],
        )
    ]
