from django.conf import settings


def get_current_organization(request):
    """
    Put things into the context.
    https://docs.djangoproject.com/en/2.1/ref/templates/api/#using-requestcontext
    """

    siae = None

    if request.user.is_authenticated:

        siae_siret = request.session.get(settings.ITOU_SESSION_CURRENT_SIAE_KEY)
        if siae_siret:
            siae = request.user.siae_set.get(siret=siae_siret)

    return {"current_siae": siae}
