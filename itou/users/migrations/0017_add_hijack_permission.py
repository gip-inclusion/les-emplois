from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0016_rename_itou_support_externe"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="user",
            options={
                "permissions": [("hijack_user", "Can impersonate (hijack) other accounts")],
                "verbose_name": "user",
                "verbose_name_plural": "users",
            },
        ),
    ]
