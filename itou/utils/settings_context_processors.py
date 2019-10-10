from django.conf import settings


def expose_settings(request):
    """
    Put things into the context to make them available in templates.
    https://docs.djangoproject.com/en/2.1/ref/templates/api/#using-requestcontext
    """

    return {"ITOU_EMAIL_CONTACT": settings.ITOU_EMAIL_CONTACT}
