from itou.companies.enums import SIAE_WITH_CONVENTION_KINDS


def get_user_last_accepted_siae_job_application(user):
    if not user.is_job_seeker:
        return None

    # Some candidates may not have accepted job applications
    # Assuming it's the case can lead to issues downstream
    return (
        user.job_applications.accepted()
        .filter(to_company__kind__in=SIAE_WITH_CONVENTION_KINDS)
        .with_accepted_at()
        .order_by("-accepted_at", "-hiring_start_at")
        .first()
    )


def last_hire_was_made_by_siae(user, siae):
    if not user.is_job_seeker:
        return False
    last_accepted_job_application = get_user_last_accepted_siae_job_application(user)
    return last_accepted_job_application and last_accepted_job_application.to_company_id == siae.pk
