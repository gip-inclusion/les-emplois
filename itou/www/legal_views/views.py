from django.contrib.auth import REDIRECT_FIELD_NAME
from django.contrib.auth.decorators import login_not_required
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from itou.utils.legal_terms import get_terms_version, get_terms_versions
from itou.utils.urls import get_safe_url


@login_not_required
def legal_terms(request, template_name="static/legal/terms/base.html"):
    user = request.user
    require_acceptance = bool(user.is_authenticated and user.must_accept_terms())
    next_url = get_safe_url(request, param_name=REDIRECT_FIELD_NAME, fallback_url=reverse("dashboard:index"))
    all_versions = get_terms_versions()
    latest_terms = all_versions[-1]
    if require_acceptance and request.method == "POST":
        terms_slug = request.POST.get("terms_slug")
        if terms_slug == latest_terms.slug:
            user.set_terms_accepted()
            return HttpResponseRedirect(next_url)
    context = {
        "require_acceptance": require_acceptance,
        "is_update": require_acceptance and user.terms_accepted_at,
        "latest_terms": latest_terms,
        "requested_terms": latest_terms,
        "all_versions": None if require_acceptance else all_versions,
        "redirect_field_name": REDIRECT_FIELD_NAME,
        "next_url": next_url,
    }
    return render(request, template_name, context=context)


@login_not_required
def legal_terms_version(request, version_slug, template_name="static/legal/terms/base.html"):
    """Render the page with the requested version of the terms & conditions ('CGU').

    This view shouldn't be very useful but keeping old versions accessible is a legal requirement.
    """
    all_versions = get_terms_versions()
    requested_version = get_terms_version(version_slug, all_versions=all_versions)
    if not requested_version:
        raise Http404
    context = {
        "require_acceptance": False,
        "is_update": False,
        "latest_terms": all_versions[-1],
        "requested_terms": requested_version,
        "all_versions": all_versions,
    }
    return render(request, template_name, context=context)
