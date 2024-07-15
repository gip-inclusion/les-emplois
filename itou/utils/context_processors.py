from urllib.parse import urlencode

from django.core.cache import cache

import itou.approvals.enums as approvals_enums
import itou.companies.enums as companies_enums
import itou.institutions.enums as institutions_enums
import itou.job_applications.enums as job_applications_enums
import itou.prescribers.enums as prescribers_enums
from itou.communications.cache import CACHE_ACTIVE_ANNOUNCEMENT_CAMPAIGN_KEY, update_active_announcement_cache


def expose_enums(*args):
    """
    Put things into the context to make them available in templates.
    https://docs.djangoproject.com/en/4.1/ref/templates/api/#using-requestcontext
    """

    return {
        "ApprovalOrigin": approvals_enums.Origin,
        "InstitutionKind": institutions_enums.InstitutionKind,
        "JobApplicationOrigin": job_applications_enums.Origin,
        "JobApplicationState": job_applications_enums.JobApplicationState,
        "PrescriberOrganizationKind": prescribers_enums.PrescriberOrganizationKind,
        "ProlongationRequestStatus": approvals_enums.ProlongationRequestStatus,
        "RefusalReason": job_applications_enums.RefusalReason,
        "SenderKind": job_applications_enums.SenderKind,
        "CompanyKind": companies_enums.CompanyKind,
    }


def matomo(request):
    context = {}
    url = request.path
    if request.resolver_match:
        url = request.resolver_match.route
    # Only keep Matomo-related params for now.
    params = {k: v for k, v in request.GET.lists() if k.startswith(("utm_", "mtm_", "piwik_"))}
    if params:
        url = f"{url}?{urlencode(sorted(params.items()), doseq=True)}"
    context["matomo_custom_url"] = url
    context["matomo_user_id"] = getattr(request.user, "pk", None)
    return context


def active_announcement_campaign(request):
    active_campaign_announce = cache.get(CACHE_ACTIVE_ANNOUNCEMENT_CAMPAIGN_KEY)
    if active_campaign_announce is None:
        active_campaign_announce = update_active_announcement_cache()
    else:
        active_campaign_announce = active_campaign_announce["value"]

    return {
        "active_campaign_announce": active_campaign_announce
        if active_campaign_announce and active_campaign_announce.items.count()
        else None
    }
