from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0004_remove_non_job_seeker_address"),
    ]

    operations = [migrations.RunSQL("TRUNCATE socialaccount_socialaccount, socialaccount_socialtoken", elidable=True)]
