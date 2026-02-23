import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from itou.utils.legal_terms import get_terms_version, get_terms_versions
from itou.utils.urls import get_safe_url


logger = logging.getLogger(__name__)


@login_not_required
def legal_terms(request, template_name="static/legal/terms/base.html"):
    user = request.user
    enforce_terms_acceptance = not getattr(settings, "BYPASS_TERMS_ACCEPTANCE", False)
    require_acceptance = enforce_terms_acceptance and user.is_authenticated and user.must_accept_terms
    next_url = get_safe_url(request, param_name="next", fallback_url=reverse("dashboard:index"))
    all_versions = get_terms_versions()
    latest_terms = all_versions[0]
    if require_acceptance and request.method == "POST":
        terms_slug = request.POST.get("terms_slug")
        if terms_slug == latest_terms.slug:
            user.terms_accepted_at = timezone.now()
            user.save(update_fields=["terms_accepted_at"])
            logger.info("user=%d accepted the latest 'CGU'", request.user.pk)
            return HttpResponseRedirect(next_url)
        else:
            # Edge case: a new version of the terms was published between the moment
            # the user loaded the page and the moment they submitted the form
            messages.warning(
                request, "Une nouvelle version des Conditions Générales d’Utilisation vient d'entrer en vigueur."
            )
    context = {
        "require_acceptance": require_acceptance,
        "is_update": require_acceptance and user.terms_accepted_at,
        "latest_terms_version": latest_terms,
        "requested_terms_version": latest_terms,
        "all_versions": None if require_acceptance else all_versions,
        "next_url": next_url,
    }
    return render(request, template_name, context=context)


@login_not_required
def legal_terms_version(request, version_slug, template_name="static/legal/terms/base.html"):
    """Render the page with the requested version of the terms & conditions ('CGU').

    Keeping old versions accessible is a legal requirement.
    """
    all_versions = get_terms_versions()
    requested_version = get_terms_version(version_slug)
    if not requested_version:
        raise Http404
    context = {
        "require_acceptance": False,
        "is_update": False,
        "latest_terms_version": all_versions[0],
        "requested_terms_version": requested_version,
        "all_versions": all_versions,
    }
    return render(request, template_name, context=context)
