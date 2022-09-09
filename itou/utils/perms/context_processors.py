from collections import OrderedDict

from django.core.exceptions import PermissionDenied
from django.urls import reverse

from itou.utils import constants as global_constants


def get_current_organization_and_perms(request):
    """
    Put things into the context to make them available in templates.
    https://docs.djangoproject.com/en/2.1/ref/templates/api/#using-requestcontext
    """

    prescriber_organization = None
    user_prescriberorganizations = []
    user_institutions = []
    current_institution = None
    siae = None
    user_is_prescriber_org_admin = False
    user_is_siae_admin = False
    user_is_institution_admin = False
    user_siaes = []

    current_user = request.user

    if current_user.is_authenticated:
        # SIAE ?
        siae_pk = request.session.get(global_constants.ITOU_SESSION_CURRENT_SIAE_KEY)
        if siae_pk:
            memberships = request.user.active_or_in_grace_period_siae_memberships()
            user_siaes = [membership.siae for membership in memberships]

            for membership in memberships:
                if membership.siae_id == siae_pk:
                    siae = membership.siae
                    user_is_siae_admin = membership.is_admin
                    break
            if siae is None:
                if request.path != reverse("account_logout"):
                    raise PermissionDenied

        # Prescriber organization ?
        prescriber_org_pk = request.session.get(global_constants.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY)

        if prescriber_org_pk:
            # Membership can now be deactivated, hence filtering on `membership.is_active` (same as SIAE above)
            memberships = (
                current_user.prescribermembership_set.filter(is_active=True)
                .order_by("created_at")
                .select_related("organization")
            )

            for membership in memberships:
                # Same as above:
                # In order to avoid an extra SQL query, fetch related organizations
                # and artifially reconstruct the list of organizations the user belongs to
                # (and other stuff while at it)
                user_prescriberorganizations.append(membership.organization)
                if membership.organization.pk == prescriber_org_pk:
                    prescriber_organization = membership.organization
                    user_is_prescriber_org_admin = membership.is_admin

        # Institution?
        institution_pk = request.session.get(global_constants.ITOU_SESSION_CURRENT_INSTITUTION_KEY)

        if institution_pk:
            memberships = (
                current_user.institutionmembership_set.filter(is_active=True)
                .order_by("created_at")
                .select_related("institution")
            )

            for membership in memberships:
                # Same as above:
                # In order to avoid an extra SQL query, fetch related institutions
                # and artificially reconstruct the list of institutions the user belongs to
                # (and other stuff while at it)
                user_institutions.append(membership.institution)
                if membership.institution.pk == institution_pk:
                    current_institution = membership.institution
                    user_is_institution_admin = membership.is_admin

    # Sort items nicely for dropdown menu.
    user_siaes.sort(key=lambda o: (o.kind, o.display_name))
    user_prescriberorganizations.sort(key=lambda o: (o.kind, o.display_name))
    user_institutions.sort(key=lambda o: (o.kind, o.display_name))

    context = {
        "current_prescriber_organization": prescriber_organization,
        "current_siae": siae,
        "current_institution": current_institution,
        "user_is_prescriber_org_admin": user_is_prescriber_org_admin,
        "user_is_siae_admin": user_is_siae_admin,
        "user_is_institution_admin": user_is_institution_admin,
        "user_siaes": user_siaes,
        "user_prescriberorganizations": user_prescriberorganizations,
        "user_institutions": user_institutions,
    }

    context.update(
        get_matomo_context(
            user=request.user,
            prescriber_organization=prescriber_organization,
            user_is_siae_admin=user_is_siae_admin,
            user_is_institution_admin=user_is_institution_admin,
        )
    )

    return context


def get_matomo_context(user, prescriber_organization, user_is_siae_admin, user_is_institution_admin):
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
    elif user.is_labor_inspector:
        account_type = "labor_inspector"
        account_sub_type = "inspector_admin" if user_is_institution_admin else "inspector_not_admin"
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
