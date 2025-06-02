from django.db import migrations


def forward(apps, editor):
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.filter(codename="hijack_user").update(codename="hijack")


def backward(apps, editor):
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.filter(codename="hijack").update(codename="hijack_user")


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0031_alter_user_options"),
    ]

    operations = [
        migrations.RunPython(forward, backward, elidable=True),
        migrations.AlterModelOptions(
            name="user",
            options={
                "permissions": [
                    ("hijack", "Can impersonate (hijack) other accounts"),
                    ("export_cta", "Can export CTA file"),
                    ("merge_users", "Can merge users"),
                ],
                "verbose_name": "user",
                "verbose_name_plural": "users",
            },
        ),
    ]
