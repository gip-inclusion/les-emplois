"""Reset ACCEPTED_ONLY_FIELDS to their empty defaults on all non-accepted JobApplications."""

import logging
import time

from django.db import migrations
from django.db.models import Q
from django.utils import timezone

from itou.job_applications.models import ACCEPTED_ONLY_FIELDS


logger = logging.getLogger(__name__)


def clear_accepted_only_fields(apps, schema_editor):
    BATCH_SIZE = 3_000
    JobApplication = apps.get_model("job_applications", "JobApplication")
    non_default_fields = [~Q(**{field: default}) for field, default in ACCEPTED_ONLY_FIELDS.items()]
    job_applications_ids = (
        JobApplication.objects.exclude(state="accepted")
        .filter(Q(*non_default_fields, _connector=Q.OR))
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    updated = 0
    while batch_job_application_ids := list(job_applications_ids[:BATCH_SIZE]):
        updated += JobApplication.objects.filter(pk__in=batch_job_application_ids).update(
            **ACCEPTED_ONLY_FIELDS,
            updated_at=timezone.now(),
        )
        time.sleep(0.2)
    logger.info("%s non-accepted job applications updated to reset accepted-only fields", updated)


class Migration(migrations.Migration):
    dependencies = [
        ("job_applications", "0006_soft_remove_jobapplication_prehiring_guidance_days"),
    ]

    operations = [
        migrations.RunPython(clear_accepted_only_fields, migrations.RunPython.noop, elidable=True),
    ]
