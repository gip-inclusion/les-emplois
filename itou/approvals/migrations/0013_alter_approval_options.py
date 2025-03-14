from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0012_fix_prolongations_declared_by_jobseeker"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="approval",
            options={
                "ordering": ["-created_at"],
                "permissions": [("export_ft_api_rejections", "Can export PASS IAE rejected by FT's API")],
                "verbose_name": "PASS\xa0IAE",
                "verbose_name_plural": "PASS\xa0IAE",
            },
        ),
    ]
