from django.conf import settings


def expose_settings(request):
    """
    Put things into the context to make them available in templates.
    https://docs.djangoproject.com/en/2.1/ref/templates/api/#using-requestcontext
    """

    full_view_name = request.resolver_match.view_name  # e.g. "home:hp" or "stats:stats_public"

    if full_view_name.startswith("stats:"):
        # On all stats pages the help button should redirect to the C2 help page instead of the C1 help page.
        assistance_url = settings.PILOTAGE_ASSISTANCE_URL
    else:
        assistance_url = settings.ITOU_ASSISTANCE_URL

    return {
        "ALLOWED_HOSTS": settings.ALLOWED_HOSTS,
        "ITOU_ASSISTANCE_URL": assistance_url,
        "ITOU_COMMUNITY_URL": settings.ITOU_COMMUNITY_URL,
        "ITOU_DOC_URL": settings.ITOU_DOC_URL,
        "ITOU_EMAIL_CONTACT": settings.ITOU_EMAIL_CONTACT,
        "ITOU_EMAIL_PROLONGATION": settings.ITOU_EMAIL_PROLONGATION,
        "ITOU_ENVIRONMENT": settings.ITOU_ENVIRONMENT,
        "ITOU_FQDN": settings.ITOU_FQDN,
        "ITOU_PILOTAGE_URL": settings.PILOTAGE_SITE_URL,
        "ITOU_PROTOCOL": settings.ITOU_PROTOCOL,
        "SHOW_TEST_ACCOUNTS_BANNER": settings.SHOW_TEST_ACCOUNTS_BANNER,
        "TYPEFORM_URL": settings.TYPEFORM_URL,
    }
