from django import template
from django.template.defaultfilters import capfirst

from itou.asp.models import RSAAllocation
from itou.companies.enums import CompanyKind
from itou.users.models import JobSeekerProfile


register = template.Library()


@register.filter(is_safe=False)
def worker_denomination(company):
    """
    Return the denomination of a worker for the company, i.e "salarié" or "travailleur indépendant".
    """
    return "travailleur indépendant" if company.kind == CompanyKind.EITI else "salarié"


@register.filter(is_safe=False)
def profile_field_display(jobseeker_profile, key):
    if getattr(jobseeker_profile, key):
        info = capfirst(JobSeekerProfile._meta.get_field(key).verbose_name)
        if key == "rsa_allocation_since":
            since_display = jobseeker_profile.get_rsa_allocation_since_display().lower()
            # Thanks to jobseekerprofile_rsa_allocation_consistency constraint, has_rsa_allocation is
            # either YES_WITH_MARKUP or YES_WITHOUT_MARKUP since rsa_allocation_since is set.
            majoration = {
                RSAAllocation.YES_WITH_MARKUP: " (majoré)",
                RSAAllocation.YES_WITHOUT_MARKUP: " (non majoré)",
            }.get(jobseeker_profile.has_rsa_allocation, "")
            return f"{info} {since_display}{majoration}"
        elif key.endswith("_since"):
            since_display = getattr(jobseeker_profile, f"get_{key}_display")().lower()
            info = f"{info} {since_display}"
        return info
    return ""
