from collections import OrderedDict

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.urls import reverse


def get_current_organization_and_perms(request):
    """
    Put things into the context to make them available in templates.
    https://docs.djangoproject.com/en/2.1/ref/templates/api/#using-requestcontext
    """

    prescriber_organization = None
    user_prescriberorganizations = []
    siae = None
    user_is_prescriber_org_admin = False
    user_is_siae_admin = False
    user_siaes = []

    current_user = request.user

    if current_user.is_authenticated:
        # SIAE ?
        siae_pk = request.session.get(settings.ITOU_SESSION_CURRENT_SIAE_KEY)
        if siae_pk:
            # Sorry I could not find an elegant DNRY one-query solution ¯\_(ツ)_/¯
            user_siae_set_pks = request.user.siae_set.active_or_in_grace_period().values_list("pk", flat=True)
            memberships = (
                request.user.siaemembership_set.select_related("siae").filter(siae__pk__in=user_siae_set_pks).all()
            )
            user_siaes = [membership.siae for membership in memberships]
            for membership in memberships:
                if membership.siae_id == siae_pk:
                    siae = membership.siae
                    user_is_siae_admin = membership.is_siae_admin
                    break
            if siae is None:
                if request.path != reverse("account_logout"):
                    raise PermissionDenied

        # Prescriber organization ?
        prescriber_org_pk = request.session.get(settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY)

        if prescriber_org_pk:
            memberships = current_user.prescribermembership_set.select_related("organization")

            for membership in memberships:
                # Same as above:
                # In order to avoid an extra SQL query, fetch related organizations
                # and artifially reconstruct the list of organizations the user belongs to
                # (and other stuff while at it)
                user_prescriberorganizations.append(membership.organization)
                if membership.organization.pk == prescriber_org_pk:
                    prescriber_organization = membership.organization
                    user_is_prescriber_org_admin = membership.is_admin

    context = {
        "current_prescriber_organization": prescriber_organization,
        "current_siae": siae,
        "user_is_prescriber_org_admin": user_is_prescriber_org_admin,
        "user_is_siae_admin": user_is_siae_admin,
        "user_siaes": user_siaes,
        "user_prescriberorganizations": user_prescriberorganizations,
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
