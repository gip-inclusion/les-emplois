from django.conf import settings
from django.db import migrations

from itou.utils.enums import ItouEnvironment


def remove_notification_date_of_evaluated_job_seekers(apps, schema_editor):
    if settings.ITOU_ENVIRONMENT != ItouEnvironment.PROD:
        return

    User = apps.get_model("users", "User")
    EvaluatedJobApplication = apps.get_model("siae_evaluations", "EvaluatedJobApplication")

    notified_and_evaluated_job_seekers_id = EvaluatedJobApplication.objects.filter(
        job_application__job_seeker__upcoming_deletion_notified_at__isnull=False
    ).values_list("job_application__job_seeker_id", flat=True)

    if notified_and_evaluated_job_seekers_id.exists():
        User.objects.filter(
            kind="job_seeker",
            upcoming_deletion_notified_at__isnull=False,
            id__in=notified_and_evaluated_job_seekers_id,
        ).update(upcoming_deletion_notified_at=None)


class Migration(migrations.Migration):
    dependencies = [
        ("archive", "0012_anonymizedcancelledapproval"),
        ("users", "0038_fix_job_seeker_profile_birthdate"),
        ("siae_evaluations", "0002_evaluatedadministrativecriteria_criteria_certified"),
    ]

    operations = [
        migrations.RunPython(
            code=remove_notification_date_of_evaluated_job_seekers,
            reverse_code=migrations.RunPython.noop,
            elidable=True,
        ),
    ]
