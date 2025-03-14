from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("job_applications", "0011_drop_hidden_for_company"),
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
