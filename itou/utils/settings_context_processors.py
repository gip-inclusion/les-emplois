from django.conf import settings


def expose_settings(request):
    """
    Put things into the context to make them available in templates.
    https://docs.djangoproject.com/en/2.1/ref/templates/api/#using-requestcontext
    """

    return {
        "ALLOWED_HOSTS": settings.ALLOWED_HOSTS,
        "ITOU_DOC_URL": settings.ITOU_DOC_URL,
        "ITOU_EMAIL_ASSISTANCE": settings.ITOU_EMAIL_ASSISTANCE,
        "ITOU_EMAIL_CONTACT": settings.ITOU_EMAIL_CONTACT,
        "ITOU_ENVIRONMENT": settings.ITOU_ENVIRONMENT,
        "ITOU_FQDN": settings.ITOU_FQDN,
        "ITOU_PROTOCOL": settings.ITOU_PROTOCOL,
        "SHOW_TEST_ACCOUNTS_BANNER": settings.SHOW_TEST_ACCOUNTS_BANNER,
    }
