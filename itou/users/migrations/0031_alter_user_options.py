from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0030_user_allow_next_sso_sub_update"),
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
