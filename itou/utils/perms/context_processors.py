from django.conf import settings


def get_current_organization(request):
    """
    Put things into the context to make them available in templates.
    https://docs.djangoproject.com/en/2.1/ref/templates/api/#using-requestcontext
    """

    siae = None
    prescriber_organization = None

    if request.user.is_authenticated:

        siae_pk = request.session.get(settings.ITOU_SESSION_CURRENT_SIAE_KEY)
        if siae_pk:
            siae = request.user.siae_set.get(pk=siae_pk)

        prescriber_org_pk = request.session.get(
            settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY
        )
        if prescriber_org_pk:
            prescriber_organization = request.user.prescriberorganization_set.get(
                pk=prescriber_org_pk
            )

    return {
        "current_siae": siae,
        "current_prescriber_organization": prescriber_organization,
    }
