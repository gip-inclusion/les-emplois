from django.conf import settings
from django.utils import timezone

from itou.companies.enums import CompanyKind
from itou.prescribers.enums import PrescriberOrganizationKind


def show_afpa_ad(user):
    return user.job_seeker_department in settings.AFPA_DEPARTMENTS


def xp_ref_iae_job_applications(request):
    # Avoid a circular import
    from itou.job_applications.models import JobApplication

    if (
        request.from_authorized_prescriber
        and request.current_organization.kind == PrescriberOrganizationKind.FT
        and request.current_organization.department == settings.XP_REF_IAE_DEPARTMENT
        and timezone.localdate() <= settings.XP_REF_IAE_END_DATE
    ):
        return JobApplication.objects.filter(
            to_company__department=settings.XP_REF_IAE_DEPARTMENT,
            to_company__kind__in=CompanyKind.siae_kinds(),
        )
    return JobApplication.objects.none()
