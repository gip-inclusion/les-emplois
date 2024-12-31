import json
import time

from django.db import migrations


def forward(apps, schema_editor):
    print()
    EmployeeRecord = apps.get_model("employee_record", "EmployeeRecord")
    total_updated = 0
    to_update = []
    for obj in EmployeeRecord.objects.filter(archived_json__isnull=False, archived_json__startswith='"{').only(
        "pk", "archived_json"
    ):
        obj.archived_json = json.loads(obj.archived_json)
        to_update.append(obj)
        if len(to_update) % 1000 == 0:
            total_updated += EmployeeRecord.objects.bulk_update(to_update, {"archived_json"})
            print(f"{total_updated} objects updated")
            to_update = []
            time.sleep(0.5)
    if to_update:
        total_updated += EmployeeRecord.objects.bulk_update(to_update, {"archived_json"})
        print(f"{total_updated} objects updated")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("employee_record", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(code=forward, reverse_code=migrations.RunPython.noop, elidable=True),
    ]
