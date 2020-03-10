from django.conf import settings
from django.core.exceptions import PermissionDenied


def get_current_organization_and_perms(request):
    """
    Put things into the context to make them available in templates.
    https://docs.djangoproject.com/en/2.1/ref/templates/api/#using-requestcontext
    """

    prescriber_organization = None
    siae = None
    user_is_prescriber_org_admin = False
    user_is_siae_admin = False
    user_siae_set = []

    if request.user.is_authenticated:

        siae_pk = request.session.get(settings.ITOU_SESSION_CURRENT_SIAE_KEY)
        if siae_pk:
            # Get all info in 1 SQL query.
            memberships = request.user.siaemembership_set.select_related("siae").all()
            user_siae_set = [membership.siae for membership in memberships]
            for membership in memberships:
                if membership.siae_id == siae_pk:
                    siae = membership.siae
                    user_is_siae_admin = membership.is_siae_admin
                    break
            if siae is None:
                raise PermissionDenied

        prescriber_org_pk = request.session.get(settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY)
        if prescriber_org_pk:
            membership = request.user.prescribermembership_set.select_related("organization").get(
                organization_id=prescriber_org_pk
            )
            prescriber_organization = membership.organization
            user_is_prescriber_org_admin = membership.is_admin

    return {
        "current_prescriber_organization": prescriber_organization,
        "current_siae": siae,
        "user_is_prescriber_org_admin": user_is_prescriber_org_admin,
        "user_is_siae_admin": user_is_siae_admin,
        "user_siae_set": user_siae_set,
    }
