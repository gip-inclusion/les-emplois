from urllib.parse import urlencode

import itou.approvals.enums as approvals_enums
import itou.companies.enums as companies_enums
import itou.job_applications.enums as job_applications_enums
import itou.prescribers.enums as prescribers_enums


def expose_enums(*args):
    """
    Put things into the context to make them available in templates.
    https://docs.djangoproject.com/en/4.1/ref/templates/api/#using-requestcontext
    """

    return {
        "ApprovalOrigin": approvals_enums.Origin,
        "JobApplicationOrigin": job_applications_enums.Origin,
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
    # only keep Matomo-related and "city" (for Site Search) GET params for now
    params = {k: v for k, v in request.GET.lists() if k in ["city"] or k.startswith(("utm_", "mtm_", "piwik_"))}
    if params:
        url = f"{url}?{urlencode(sorted(params.items()), doseq=True)}"
    context["matomo_custom_url"] = url
    if request.user:
        context["matomo_user_id"] = request.user.pk
    return context
