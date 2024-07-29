import datetime
import time

from django.db import migrations
from django.utils import timezone


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def forward(apps, editor):
    JobApplication = apps.get_model("job_applications", "JobApplication")
    BATCH_SIZE = 10_000
    now = timezone.now()
    six_months_ago = now - datetime.timedelta(days=180)
    total = 0
    start = time.perf_counter()

    archivable_states = ["new", "processing", "postponed", "refused", "cancelled", "obsolete"]

    archivable = list(
        JobApplication.objects.filter(
            state__in=archivable_states,
            updated_at__lte=six_months_ago,
            archived_at=None,
        ).values_list("pk", flat=True)
    )
    print()
    for chunk in chunks(archivable, BATCH_SIZE):
        matched = JobApplication.objects.filter(pk__in=chunk).update(archived_at=now)
        total += matched
        print(f"Archived {total} job applications, elapsed {time.perf_counter() - start}s")
        time.sleep(1)

    start = time.perf_counter()
    matched = JobApplication.objects.filter(
        hidden_for_company=True,
        state__in=archivable_states,
        archived_at=None,
    ).update(archived_at=now)
    print(f"Migrated {matched} hidden for company in {time.perf_counter() - start}s")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("job_applications", "0009_jobapplication_archived_at"),
    ]

    operations = [
        migrations.RunPython(
            forward,
            migrations.RunPython.noop,
            elidable=True,
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.RemoveField(model_name="jobapplication", name="hidden_for_company")],
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE job_applications_jobapplication ALTER COLUMN hidden_for_company SET DEFAULT false"
                )
            ],
        ),
    ]
