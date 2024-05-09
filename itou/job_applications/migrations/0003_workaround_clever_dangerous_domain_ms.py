import time

from django.db import migrations
from django.db.models import Value
from django.db.models.functions import Concat, Substr


def forwards(apps, editor):
    print()
    JobApplication = apps.get_model("job_applications", "JobApplication")
    total = 0
    start = time.perf_counter()
    updated = True
    while updated:
        slice = JobApplication.objects.filter(
            resume_link__startswith="https://cellar-c2.services.clever-cloud.com/",
        )[:20_000]
        updated = JobApplication.objects.filter(pk__in=slice).update(
            resume_link=Concat(
                Value("https://par.cellar.clever-cloud.com"),
                Substr("resume_link", len("https://cellar-c2.services.clever-cloud.com") + 1),
            )
        )
        total += updated
        if updated:
            print(f"Updated {total} job applications, migration duration {time.perf_counter() - start:.2f}s")
            time.sleep(1)


class Migration(migrations.Migration):
    """
    The domain cellar-c2.services.clever-cloud.com has been flagged as dangerous by Microsoft.

    Apply Clever workaround to use another domain.
    """

    atomic = False

    dependencies = [
        ("job_applications", "0002_jobapplication_refusal_reason_shared_with_job_seeker"),
    ]

    operations = [migrations.RunPython(forwards, elidable=True)]
