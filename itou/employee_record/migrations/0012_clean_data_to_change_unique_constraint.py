from django.db import migrations
from django.db.models import Count


def clean_data(apps, schema_editor):
    EmployeeRecord = apps.get_model("employee_record", "EmployeeRecord")
    EmployeeRecordUpdateNotification = apps.get_model("employee_record", "EmployeeRecordUpdateNotification")
    # Build needed querysets
    not_unique_approval_numbers = (
        EmployeeRecord.objects.values("asp_measure", "siret", "approval_number")
        .annotate(count=Count("pk"))
        .filter(count__gt=1)
        .values_list("approval_number", flat=True)
    )
    curated_not_unique_objects_qs = EmployeeRecord.objects.filter(
        # The associated convention is not active anymore,
        # not doing something smarter to let the constraint failed if needed.
        siret="37882551700030",
        asp_id="921",
        asp_measure="AI_DC",
        approval_number__in=not_unique_approval_numbers,
    )
    linked_notifications_qs = EmployeeRecordUpdateNotification.objects.filter(
        employee_record__in=curated_not_unique_objects_qs.values("pk")
    )
    # Delete the curated employee records and theirs notifications
    linked_notifications_qs.delete()
    curated_not_unique_objects_qs.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("employee_record", "0011_clean_orphans_duplicate"),
    ]

    operations = [
        migrations.RunPython(clean_data, reverse_code=migrations.RunPython.noop, elidable=True),
    ]
