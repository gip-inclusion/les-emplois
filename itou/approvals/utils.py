import datetime

from django.db.models import Max, Q
from django.utils import timezone

from itou.companies.enums import CompanyKind
from itou.companies.models import Contract


# A PASS IAE is eligible for closure when its suspension has been going on for
# at least this duration without interruption.
SUSPENSION_DURATION_BEFORE_APPROVAL_CLOSABLE = datetime.timedelta(days=365)


def can_close_approval(approval):
    """Return True when *approval* meets all three conditions for a user-initiated closure:

    1. At least one suspension has been running (or ran) for more than 12
       consecutive months, and no accepted hiring occurred after it ended.
    2. The job seeker has no pending applications in the last 60 days.
    3. The job seeker has no ongoing contract in the ASP data.
    """
    today = timezone.localdate()

    long_suspensions = [
        suspension
        for suspension in approval.suspension_set.all()
        if (today - suspension.start_at if suspension.is_in_progress else suspension.duration)
        > SUSPENSION_DURATION_BEFORE_APPROVAL_CLOSABLE
    ]

    if any(suspension.is_in_progress for suspension in long_suspensions):
        long_suspension = True
    elif long_suspensions:
        last_hiring_start_at = approval.jobapplication_set.accepted().aggregate(Max("hiring_start_at"))[
            "hiring_start_at__max"
        ]
        long_suspension = last_hiring_start_at is None or any(
            suspension.end_at > last_hiring_start_at for suspension in long_suspensions
        )
    else:
        return False

    if not long_suspension:
        return False

    if (
        approval.user.job_applications.pending()
        .filter(created_at__date__gte=today - datetime.timedelta(days=60))
        .exists()
    ):
        return False

    return not Contract.objects.filter(
        Q(end_date__isnull=True) | Q(end_date__gte=today),
        job_seeker=approval.user,
    ).exists()


def get_user_last_accepted_siae_job_application(user):
    if not user.is_job_seeker:
        return None

    # Some candidates may not have accepted job applications
    # Assuming it's the case can lead to issues downstream
    return (
        user.job_applications.accepted()
        .filter(to_company__kind__in=CompanyKind.siae_kinds())
        .with_accepted_at()
        .order_by("-accepted_at", "-hiring_start_at")
        .first()
    )


def last_hire_was_made_by_siae(user, siae):
    if not user.is_job_seeker:
        return False
    last_accepted_job_application = get_user_last_accepted_siae_job_application(user)
    return last_accepted_job_application and last_accepted_job_application.to_company_id == siae.pk


def get_contracts(approval):
    return (
        Contract.objects.filter(job_seeker=approval.user)
        # Filter out contracts that do not overlap the approval
        .exclude(end_date__lt=approval.start_at)
        .exclude(start_date__gt=approval.end_at)
        .select_related("company")
        .order_by("-start_date")
    )
