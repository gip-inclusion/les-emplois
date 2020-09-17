import time

import jwt
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.core.exceptions import PermissionDenied

# Embedding Metabase dashboards:
# Metabase dashboards can be included securely in the app via a signed URL
# See an embedding sample at:
# https://github.com/metabase/embedding-reference-apps/blob/master/django/embedded_analytics/user_stats/views.py


# Each signed dashboard has the same look (at the moment)
_STATS_HTML_TEMPLATE = "stats/stats.html"


def _get_token(payload):
    return jwt.encode(payload, settings.METABASE_SECRET_KEY, algorithm="HS256").decode("utf8")


def _signed_dashboard_embedded_url(dashboard_number):
    payload = {"resource": {"dashboard": dashboard_number}, "params": {}, "exp": round(time.time()) + (60 * 10)}
    return settings.METABASE_SITE_URL + "/embed/dashboard/" + _get_token(payload)


@login_required
def public_stats(request, template_name=_STATS_HTML_TEMPLATE):
    """
    Public stats are now signed and embedded (no more public links)
    """
    context = {"iframeurl": _signed_dashboard_embedded_url(34)}
    return render(request, template_name, context)


@login_required
def advanced_stats(request, template_name=_STATS_HTML_TEMPLATE):
    """
    "Advanced" stats reporting data (signed)

    """
    if not request.user.is_reporting:
        raise PermissionDenied

    context = {"iframeurl": _signed_dashboard_embedded_url(43)}
    return render(request, template_name, context)


@login_required
def reporting(request, template_name=_STATS_HTML_TEMPLATE):
    """
    If the user has the 'is_reporting' flag, this Metabase dashboard link
    is displayed on the dashboard page
    """
    if not request.user.is_reporting:
        raise PermissionDenied

    context = {"iframeurl": _signed_dashboard_embedded_url(36)}
    return render(request, template_name, context)
