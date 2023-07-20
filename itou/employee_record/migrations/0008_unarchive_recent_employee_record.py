from dateutil.relativedelta import relativedelta
from django.db import migrations
from django.db.models import Q
from django.utils import timezone

from itou.employee_record.enums import Status


def unarchive(apps, schema_editor):
    """Put back recently created (and archived) employee records.

    SELECT asp_processing_code, processed_as_duplicate, COUNT(id)
    FROM employee_record_employeerecord
    WHERE status = 'ARCHIVED' AND created_at >= NOW() - interval '6 months'
    GROUP BY 1, 2
    ORDER BY 1, 2;
     asp_processing_code | processed_as_duplicate | count
    ---------------------+------------------------+-------
     0000                | f                      |   565
     3308                | f                      |     1
     3417                | f                      |     1
     3418                | f                      |     1
     3419                | f                      |     1
     3435                | f                      |     3
     3436                | t                      |   153
     3437                | f                      |    10
                         | f                      |   165
    (9 rows)
    """
    EmployeeRecord = apps.get_model("employee_record", "EmployeeRecord")
    base_qs = EmployeeRecord.objects.filter(
        status=Status.ARCHIVED,
        created_at__gte=timezone.now() - relativedelta(months=6),
    )
    # Correctly processed / 0000
    base_qs.filter(asp_processing_code="0000").update(status=Status.PROCESSED)
    # Processed as duplicate / 3436
    base_qs.filter(asp_processing_code="3436", processed_as_duplicate=True).update(status=Status.PROCESSED)
    # In error
    base_qs.filter(asp_processing_code__isnull=False).exclude(
        Q(asp_processing_code="0000") | Q(asp_processing_code="3436", processed_as_duplicate=True)
    ).update(status=Status.REJECTED)
    # Put others to NEW
    base_qs.filter(asp_processing_code=None).update(status=Status.NEW)


class Migration(migrations.Migration):
    dependencies = [
        ("employee_record", "0007_make_unique_asp_id_approval_number_non_partial"),
    ]

    operations = [migrations.RunPython(unarchive, reverse_code=migrations.RunPython.noop, elidable=True)]
