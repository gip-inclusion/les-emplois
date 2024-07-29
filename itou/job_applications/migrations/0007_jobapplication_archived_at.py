import datetime
import time

from django.db import migrations, models
from django.utils import timezone


def forward(apps, editor):
    JobApplication = apps.get_model("job_applications", "JobApplication")
    BATCH_SIZE = 10_000
    now = timezone.now()
    six_months_ago = now - datetime.timedelta(days=183)
    total = 0
    start = time.perf_counter()

    print()
    while True:
        chunk = JobApplication.objects.filter(
            state__in=["new", "processing", "postponed", "refused", "cancelled", "obsolete"],
            updated_at__lte=six_months_ago,
            archived_at=None,
        )[:BATCH_SIZE]
        if not chunk:
            break

        job_apps = []
        for job_app in chunk:
            job_app.archived_at = now
            job_apps.append(job_app)
        JobApplication.objects.bulk_update(job_apps, fields=["archived_at"])
        print(f"Archived {total + len(job_apps)} job applications, elapsed {time.perf_counter() - start}s")
        total += len(job_apps)
        time.sleep(1)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("job_applications", "0006_jobapplication_processed_coherence"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobapplication",
            name="archived_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True, verbose_name="archivée le"),
        ),
        migrations.RunPython(
            forward,
            migrations.RunPython.noop,
            elidable=True,
        ),
        migrations.AddConstraint(
            model_name="jobapplication",
            constraint=models.CheckConstraint(
                check=models.Q(("archived_at__isnull", False), ("state", "accepted"), _negated=True),
                name="archived_not_accepted",
                violation_error_message="Impossible d’archiver une candidature acceptée.",
            ),
        ),
    ]
