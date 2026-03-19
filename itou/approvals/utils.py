from itou.companies.enums import CompanyKind
from itou.companies.models import Contract


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
