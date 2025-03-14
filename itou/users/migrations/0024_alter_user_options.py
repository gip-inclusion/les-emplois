from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0023_jobseekerprofile_created_by_prescriber_organization"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="user",
            options={
                "permissions": [
                    ("hijack_user", "Can impersonate (hijack) other accounts"),
                    ("export_cta", "Can export CTA file"),
                    ("merge_users", "Can merge users"),
                ],
                "verbose_name": "user",
                "verbose_name_plural": "users",
            },
        ),
    ]
