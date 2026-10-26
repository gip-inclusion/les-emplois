from django.conf import settings
from django.utils import timezone

from itou.companies.enums import CompanyKind
from itou.utils.perms.prescriber import is_authorized_ft_prescriber


def show_afpa_ad(user):
    return user.job_seeker_department in settings.AFPA_DEPARTMENTS


def xp_ref_iae_job_applications(request):
    # Avoid a circular import
    from itou.job_applications.models import JobApplication

    if (
        is_authorized_ft_prescriber(request)
        and request.current_organization.department in settings.XP_REF_IAE_DEPARTMENTS
        and timezone.localdate() <= settings.XP_REF_IAE_END_DATE
    ):
        return JobApplication.objects.filter(
            to_company__department=request.current_organization.department,
            to_company__kind__in=CompanyKind.siae_kinds(),
        )
    return JobApplication.objects.none()
