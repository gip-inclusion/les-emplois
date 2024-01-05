from django.db import migrations
from django.db.models import Count, F


def _clean_orphans_duplicate(apps, schema_editor):
    EmployeeRecord = apps.get_model("employee_record", "EmployeeRecord")

    ja_with_multiple_er = (
        EmployeeRecord.objects.values("job_application")
        .annotate(cnt=Count("job_application"))
        .filter(cnt__gt=1)
        .values_list("job_application", flat=True)
    )
    print(f"Found {ja_with_multiple_er.count()} job applications with more than 1 employee record")
    for ja_pk in ja_with_multiple_er:
        all_related_er = EmployeeRecord.objects.filter(job_application=ja_pk)
        orphaned_er = all_related_er.orphans()

        # Fewer orphans than non-orphans, we can safely delete the orphans
        if orphaned_er.count() < all_related_er.count():
            print(f"Deleting all orphans for job_application={ja_pk}: {orphaned_er.values_list('pk', flat=True)}")
            orphaned_er.delete()
            continue

        # Same numbers of orphans than non-orphans, keep the last one (probably :P)
        # Using `asp_batch_file` because it holds the timestamp of when it was sent while `updated_at` and
        # `created_at` can have been touched, putting nulls last to prefer employee records that were really sent.
        to_delete = orphaned_er.order_by(
            F("asp_batch_file").desc(nulls_last=True),
            "-updated_at",
            "-created_at",
        )[1:].values_list("pk", flat=True)  # fmt: skip
        print(f"Deleting oldest orphans for job_application={ja_pk}: {to_delete}")
        EmployeeRecord.objects.filter(pk__in=to_delete).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("employee_record", "0010_add_asp_measure_to_unique_constraint"),
    ]

    operations = [
        migrations.RunPython(_clean_orphans_duplicate, reverse_code=migrations.RunPython.noop, elidable=True),
    ]
