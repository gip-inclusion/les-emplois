from django.db import migrations


def _rename_itou_support_externe(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name="itou-support-externe").update(name="itou-admin-readonly")


def _rename_itou_admin_readonly(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name="itou-admin-readonly").update(name="itou-support-externe")


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0015_employee_record_eiti_fields"),
    ]

    operations = [
        migrations.RunPython(_rename_itou_support_externe, _rename_itou_admin_readonly, elidable=True),
    ]
