from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0028_user_upcoming_deletion_notified_at"),
    ]

    operations = [
        migrations.RunSQL(
            """
        CREATE VIEW users_jobseeker
            AS SELECT user_id AS user_ptr_id, * FROM users_jobseekerprofile
            WITH CASCADED CHECK OPTION
        """,
            "DROP VIEW users_jobseeker",
        )
    ]
