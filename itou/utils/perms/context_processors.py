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
    matomo_custom_var_is_authenticated = "yes" if user.is_authenticated else "no"

    if not user.is_authenticated:
        matomo_custom_var_account_type = "anonymous"
        matomo_custom_var_account_sub_type = "anonymous"
    elif user.is_job_seeker:
        matomo_custom_var_account_type = "job_seeker"
        matomo_custom_var_account_sub_type = "peconnect" if user.is_peamu else "not_peconnect"
    elif user.is_prescriber:
        matomo_custom_var_account_type = "prescriber"
        if prescriber_organization:
            matomo_custom_var_account_sub_type = (
                "authorized_org" if prescriber_organization.is_authorized else "unauthorized_org"
            )
        else:
            matomo_custom_var_account_sub_type = "without_org"
    elif user.is_siae_staff:
        matomo_custom_var_account_type = "employer"
        matomo_custom_var_account_sub_type = "admin" if user_is_siae_admin else "not_admin"
    else:
        matomo_custom_var_account_type = "unknown"
        matomo_custom_var_account_sub_type = "unknown"

    return {
        "matomo_custom_var_is_authenticated": matomo_custom_var_is_authenticated,
        "matomo_custom_var_account_type": matomo_custom_var_account_type,
        "matomo_custom_var_account_sub_type": matomo_custom_var_account_sub_type,
    }
