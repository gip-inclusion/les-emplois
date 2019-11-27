from django.conf import settings


def get_current_organization_and_perms(request):
    """
    Put things into the context to make them available in templates.
    https://docs.djangoproject.com/en/2.1/ref/templates/api/#using-requestcontext
    """

    siae = None
    prescriber_organization = None
    user_is_siae_admin = False
    user_is_prescriber_org_admin = False

    if request.user.is_authenticated:

        siae_pk = request.session.get(settings.ITOU_SESSION_CURRENT_SIAE_KEY)
        if siae_pk:
            siaemembership = request.user.siaemembership_set.select_related("siae").get(
                siae_id=siae_pk
            )
            siae = siaemembership.siae
            user_is_siae_admin = siaemembership.is_siae_admin

        prescriber_org_pk = request.session.get(
            settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY
        )
        if prescriber_org_pk:
            prescribermembership = request.user.prescribermembership_set.select_related(
                "organization"
            ).get(organization_id=prescriber_org_pk)
            prescriber_organization = prescribermembership.organization
            user_is_prescriber_org_admin = prescribermembership.is_admin

    return {
        "current_siae": siae,
        "current_prescriber_organization": prescriber_organization,
        "user_is_siae_admin": user_is_siae_admin,
        "user_is_prescriber_org_admin": user_is_prescriber_org_admin,
    }
