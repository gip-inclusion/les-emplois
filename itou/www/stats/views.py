from django.conf import settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from itou.utils.urls import metabase_embedded_url


# Embedding Metabase dashboards:
# Metabase dashboards can be included securely in the app via a signed URL
# See an embedding sample at:
# https://github.com/metabase/embedding-reference-apps/blob/master/django/embedded_analytics/user_stats/views.py

# Each signed dashboard has the same look (at the moment)
_STATS_HTML_TEMPLATE = "stats/stats.html"

# Metabase dashboard IDs
PUBLIC_STATS_DASHBOARD_ID = 34
ADVANCED_STATS_DASHBOARD_ID = 43
DIRECCTE_STATS_DASHBOARD_ID = 36


def can_view_stats(user):
    return user.is_stats_vip


@login_required
def public_stats(request, template_name=_STATS_HTML_TEMPLATE):
    """
    Public stats (signed and embedded version)
    Public link:
    https://stats.inclusion.beta.gouv.fr/public/dashboard/f1527a13-1508-498d-8014-b2fe487a3a70
    """
    context = {
        "iframeurl": metabase_embedded_url(PUBLIC_STATS_DASHBOARD_ID),
        "stats_base_url": settings.METABASE_SITE_URL,
    }
    return render(request, template_name, context)


@login_required
def advanced_stats(request, template_name=_STATS_HTML_TEMPLATE):
    """
    "Advanced" stats reporting data (signed and embedded version)
    Public link:
    https://stats.inclusion.beta.gouv.fr/public/dashboard/c65faf79-3b89-4416-9faa-ff5182f41468
    """
    context = {
        "iframeurl": metabase_embedded_url(ADVANCED_STATS_DASHBOARD_ID),
        "stats_base_url": settings.METABASE_SITE_URL,
    }
    return render(request, template_name, context)


@login_required
@user_passes_test(can_view_stats, login_url="/dashboard")
def reporting(request, template_name=_STATS_HTML_TEMPLATE):
    """
    If the user has the 'is_stats_vip' flag, this Metabase dashboard link
    is displayed on the dashboard page
    """
    context = {
        "iframeurl": metabase_embedded_url(DIRECCTE_STATS_DASHBOARD_ID),
        "stats_base_url": settings.METABASE_SITE_URL,
    }
    return render(request, template_name, context)
