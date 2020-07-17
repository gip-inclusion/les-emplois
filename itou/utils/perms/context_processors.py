from collections import OrderedDict

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
                    # FIXME has_expired
                    siae = membership.siae
                    user_is_siae_admin = membership.is_siae_admin
                    break
            # FIXME all siaes have expired
            if siae is None:
                raise PermissionDenied

        prescriber_org_pk = request.session.get(settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY)
        if prescriber_org_pk:
            membership = request.user.prescribermembership_set.select_related("organization").get(
                organization_id=prescriber_org_pk
            )
            prescriber_organization = membership.organization
            user_is_prescriber_org_admin = membership.is_admin

    context = {
        "current_prescriber_organization": prescriber_organization,
        "current_siae": siae,
        "user_is_prescriber_org_admin": user_is_prescriber_org_admin,
        "user_is_siae_admin": user_is_siae_admin,
        "user_siae_set": user_siae_set,
    }
    context.update(
        get_matomo_context(
            user=request.user, prescriber_organization=prescriber_organization, user_is_siae_admin=user_is_siae_admin
        )
    )
    return context


def get_matomo_context(user, prescriber_organization, user_is_siae_admin):
    is_authenticated = "yes" if user.is_authenticated else "no"

    if not user.is_authenticated:
        account_type = "anonymous"
        account_sub_type = "anonymous"
    elif user.is_job_seeker:
        account_type = "job_seeker"
        account_sub_type = "job_seeker_with_peconnect" if user.is_peamu else "job_seeker_without_peconnect"
    elif user.is_prescriber:
        account_type = "prescriber"
        if prescriber_organization:
            account_sub_type = (
                "prescriber_with_authorized_org"
                if prescriber_organization.is_authorized
                else "prescriber_with_unauthorized_org"
            )
        else:
            account_sub_type = "prescriber_without_org"
    elif user.is_siae_staff:
        account_type = "employer"
        account_sub_type = "employer_admin" if user_is_siae_admin else "employer_not_admin"
    else:
        account_type = "unknown"
        account_sub_type = "unknown"

    matomo_custom_variables = OrderedDict(
        [
            ("is_authenticated", is_authenticated),
            ("account_type", account_type),
            ("account_sub_type", account_sub_type),
        ]
    )

    return {"matomo_custom_variables": matomo_custom_variables}
