from django.conf import settings

from itou.utils import constants as global_constants


def expose_settings(request):
    """
    Put things into the context to make them available in templates.
    https://docs.djangoproject.com/en/4.1/ref/templates/api/#using-requestcontext
    """

    help_center_url = global_constants.ITOU_HELP_CENTER_URL

    resolver_match = request.resolver_match
    if resolver_match is not None:  # resolver_match is None for some routes e.g. /robots.txt
        full_view_name = resolver_match.view_name  # e.g. "search:employers_home" or "stats:stats_public"
        if full_view_name.startswith("stats:"):
            # On all stats pages the help button should redirect to the C2 help page instead of the C1 help page.
            help_center_url = global_constants.PILOTAGE_HELP_CENTER_URL

    return {
        "ALLOWED_HOSTS": settings.ALLOWED_HOSTS,
        "API_EMAIL_CONTACT": settings.API_EMAIL_CONTACT,
        "ITOU_HELP_CENTER_URL": help_center_url,
        "ITOU_EMAIL_CONTACT": settings.ITOU_EMAIL_CONTACT,
        "ITOU_ENVIRONMENT": settings.ITOU_ENVIRONMENT,
        "ITOU_FQDN": settings.ITOU_FQDN,
        "ITOU_PILOTAGE_URL": global_constants.PILOTAGE_SITE_URL,
        "ITOU_PROTOCOL": settings.ITOU_PROTOCOL,
        "MATOMO_BASE_URL": settings.MATOMO_BASE_URL,
        "MATOMO_SITE_ID": global_constants.MATOMO_SITE_EMPLOIS_ID,
        "SHOW_DEMO_ACCOUNTS_BANNER": settings.SHOW_DEMO_ACCOUNTS_BANNER,
    }
