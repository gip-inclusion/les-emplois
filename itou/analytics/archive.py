from django.db.models import Count, Q
from django.utils import timezone

from itou.analytics.models import DatumCode
from itou.archive.management.commands.notify_inactive_jobseekers import (
    inactive_jobseekers_without_recent_related_objects,
)
from itou.archive.models import (
    AnonymizedApplication,
    AnonymizedApproval,
    AnonymizedCancelledApproval,
    AnonymizedGEIQEligibilityDiagnosis,
    AnonymizedJobSeeker,
    AnonymizedProfessional,
    AnonymizedSIAEEligibilityDiagnosis,
)
from itou.users.models import User, UserKind
from itou.utils.constants import INACTIVITY_PERIOD


def collect_archive_data():
    inactive_since = timezone.now() - INACTIVITY_PERIOD
    counts = User.objects.aggregate(
        anonymized_professionals_not_deleted=Count(
            "pk",
            filter=Q(
                kind__in=UserKind.professionals(), upcoming_deletion_notified_at__isnull=False, email__isnull=True
            ),
        ),
        notified_job_seekers=Count(
            "pk",
            filter=Q(kind=UserKind.JOB_SEEKER, upcoming_deletion_notified_at__isnull=False),
        ),
        notified_professionals=Count(
            "pk",
            filter=Q(
                kind__in=UserKind.professionals(),
                upcoming_deletion_notified_at__isnull=False,
                email__isnull=False,
            ),
        ),
        notifiable_professionals=Count(
            "pk",
            filter=Q(
                kind__in=UserKind.professionals(),
                upcoming_deletion_notified_at__isnull=True,
                last_login__lt=inactive_since,
            ),
        ),
    )

    return {
        DatumCode.ANONYMIZED_PROFESSIONALS_DELETED: AnonymizedProfessional.objects.count(),
        DatumCode.ANONYMIZED_PROFESSIONALS_NOT_DELETED: counts["anonymized_professionals_not_deleted"],
        DatumCode.ANONYMIZED_JOB_SEEKERS: AnonymizedJobSeeker.objects.count(),
        DatumCode.ANONYMIZED_APPLICATIONS: AnonymizedApplication.objects.count(),
        DatumCode.ANONYMIZED_APPROVALS: AnonymizedApproval.objects.count(),
        DatumCode.ANONYMIZED_CANCELLED_APPROVALS: AnonymizedCancelledApproval.objects.count(),
        DatumCode.ANONYMIZED_IAE_ELIGIBILITY_DIAGNOSIS: AnonymizedSIAEEligibilityDiagnosis.objects.count(),
        DatumCode.ANONYMIZED_GEIQ_ELIGIBILITY_DIAGNOSIS: AnonymizedGEIQEligibilityDiagnosis.objects.count(),
        DatumCode.NOTIFIED_PROFESSIONALS: counts["notified_professionals"],
        DatumCode.NOTIFIED_JOB_SEEKERS: counts["notified_job_seekers"],
        DatumCode.NOTIFIABLE_PROFESSIONALS: counts["notifiable_professionals"],
        DatumCode.NOTIFIABLE_JOB_SEEKERS: inactive_jobseekers_without_recent_related_objects(
            inactive_since=inactive_since, notified=False
        ).count(),
    }
