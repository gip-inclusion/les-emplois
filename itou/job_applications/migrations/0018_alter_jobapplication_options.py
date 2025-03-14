from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("job_applications", "0017_jobapplication_job_seeker_sender_coherence"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="jobapplication",
            options={
                "ordering": ["-created_at"],
                "permissions": [
                    (
                        "export_job_applications_unknown_to_ft",
                        "Can export job applications of job seekers unknown to FT",
                    )
                ],
                "verbose_name": "candidature",
            },
        ),
    ]
