from django.conf import settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from itou.utils.address.departments import DEPARTMENTS
from itou.utils.apis.metabase import metabase_embedded_url
from itou.utils.perms.decorators import can_view_stats_vip
from itou.utils.perms.prescriber import get_current_org_or_404


# Embedding Metabase dashboards:
# Metabase dashboards can be included securely in the app via a signed URL
# See an embedding sample at:
# https://github.com/metabase/embedding-reference-apps/blob/master/django/embedded_analytics/user_stats/views.py

# Each signed dashboard has the same look (at the moment)
_STATS_HTML_TEMPLATE = "stats/stats.html"


def public_basic_stats(request, template_name=_STATS_HTML_TEMPLATE):
    """
    Public basic stats (signed and embedded version)
    Public link:
    https://stats.inclusion.beta.gouv.fr/public/dashboard/f1527a13-1508-498d-8014-b2fe487a3a70
    """
    context = {
        "iframeurl": metabase_embedded_url(settings.PUBLIC_BASIC_STATS_DASHBOARD_ID),
        "page_title": "Statistiques",
        "related_link": "stats:public_advanced_stats",
        "related_title": "Vers les statistiques avancées",
        "stats_base_url": settings.METABASE_SITE_URL,
    }
    return render(request, template_name, context)


def public_advanced_stats(request, template_name=_STATS_HTML_TEMPLATE):
    """
    Public advanced stats (signed and embedded version)
    Public link:
    https://stats.inclusion.beta.gouv.fr/public/dashboard/c65faf79-3b89-4416-9faa-ff5182f41468
    """
    context = {
        "iframeurl": metabase_embedded_url(settings.PUBLIC_ADVANCED_STATS_DASHBOARD_ID),
        "page_title": "Statistiques avancées",
        "related_link": "stats:public_basic_stats",
        "related_title": "Vers les statistiques simplifiées",
        "stats_base_url": settings.METABASE_SITE_URL,
    }
    return render(request, template_name, context)


@login_required
@user_passes_test(can_view_stats_vip, login_url="/dashboard")
def stats_vip(request, template_name=_STATS_HTML_TEMPLATE):
    """
    Legacy stats only available to vip users.
    Will most likely be dropped soon.
    """
    context = {
        "iframeurl": metabase_embedded_url(settings.VIP_STATS_DASHBOARD_ID),
        "page_title": "Données par territoire",
        "stats_base_url": settings.METABASE_SITE_URL,
    }
    return render(request, template_name, context)


@login_required
def stats_cd(request, template_name=_STATS_HTML_TEMPLATE):
    """
    CD ("Conseil Départemental") stats shown to relevant CD members.
    They can only view data for their own departement.

    Important: "département" field should be locked on metabase side.
    Go to https://stats.inclusion.beta.gouv.fr/dashboard/XXX then "Partage" then "Partager et intégrer" then
    "Intégrer ce dashboard dans une application" then inside "Paramètres" on the right, make sure the relevant
    parameter "Département" is "Verrouillé" and "Région" is "Désactivé".
    """
    current_org = get_current_org_or_404(request)
    if not request.user.can_view_stats_cd(current_org=current_org):
        raise PermissionDenied
    department = current_org.department
    context = {
        "iframeurl": metabase_embedded_url(settings.CD_STATS_DASHBOARD_ID, department=department),
        "page_title": f"Données de mon département : {DEPARTMENTS[department]}",
        "stats_base_url": settings.METABASE_SITE_URL,
    }
    return render(request, template_name, context)
