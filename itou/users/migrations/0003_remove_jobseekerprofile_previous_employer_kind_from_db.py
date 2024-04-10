from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0002_remove_jobseekerprofile_previous_employer_kind"),
    ]

    operations = [
        migrations.RunSQL("ALTER TABLE users_jobseekerprofile DROP COLUMN previous_employer_kind"),
    ]
