from django.conf import settings


def get_current_organization(request):
    """
    Put things into the context to make them available in templates.
    https://docs.djangoproject.com/en/2.1/ref/templates/api/#using-requestcontext
    """

    siae = None
    prescriber_organization = None

    if request.user.is_authenticated:

        siae_siret = request.session.get(settings.ITOU_SESSION_CURRENT_SIAE_KEY)
        if siae_siret:
            siae = request.user.siae_set.get(siret=siae_siret)

        prescriber_organization_siret = request.session.get(
            settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY
        )
        if prescriber_organization_siret:
            prescriber_organization = request.user.prescriberorganization_set.get(
                siret=prescriber_organization_siret
            )

    return {
        "current_siae": siae,
        "current_prescriber_organization": prescriber_organization,
    }
