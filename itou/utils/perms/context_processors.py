from django.core.exceptions import PermissionDenied
from django.urls import reverse

from itou.utils import constants as global_constants


def join_keys_str(collection):
    return ";".join(str(o.pk) for o in collection)


def sort_organizations(collection):
    return sorted(collection, key=lambda o: (o.kind, o.display_name))


def get_current_organization_and_perms(request):
    siae_pk = request.session.get(global_constants.ITOU_SESSION_CURRENT_SIAE_KEY)
    prescriber_org_pk = request.session.get(global_constants.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY)
    institution_pk = request.session.get(global_constants.ITOU_SESSION_CURRENT_INSTITUTION_KEY)

    if request.user.is_authenticated:
        context, extra_context, extra_matomo_context = {}, {}, {}
        matomo_context = {"is_authenticated": "yes"} | user_to_account_type(request.user)

        if siae_pk:
            extra_context, extra_matomo_context = get_context_siae(request.user, siae_pk)
            if "current_siae" not in extra_context and request.path != reverse("account_logout"):
                raise PermissionDenied

        if prescriber_org_pk:
            extra_context, extra_matomo_context = get_context_prescriber(request.user, prescriber_org_pk)

        if institution_pk:
            extra_context, extra_matomo_context = get_context_institution(request.user, institution_pk)

        context.update(extra_context)
        return context | {"matomo_custom_variables": matomo_context | extra_matomo_context}

    return {
        "matomo_custom_variables": {
            "is_authenticated": "no",
            "account_type": "anonymous",
            "account_sub_type": "anonymous",
        }
    }


def get_context_siae(user, siae_pk):
    context = {}
    matomo_context = {}
    memberships = user.active_or_in_grace_period_siae_memberships()
    siaes = []
    for membership in memberships:
        siaes.append(membership.siae)
        if membership.siae_id == siae_pk:
            matomo_context.update(
                {
                    "account_current_siae_id": siae_pk,
                    "account_sub_type": "employer_admin" if membership.is_admin else "employer_not_admin",
                }
            )
            context.update(
                {
                    "current_siae": membership.siae,
                    "user_is_siae_admin": membership.is_admin,
                }
            )
    context["user_siaes"] = sort_organizations(siaes)
    matomo_context["account_siae_ids"] = join_keys_str(context["user_siaes"])
    return context, matomo_context


def get_context_prescriber(user, prescriber_org_pk):
    context = {}
    matomo_context = {}
    memberships = (
        user.prescribermembership_set.filter(is_active=True).order_by("created_at").select_related("organization")
    )

    prescriber_orgs = []
    for membership in memberships:
        # Same as above:
        # In order to avoid an extra SQL query, fetch related organizations
        # and artifially reconstruct the list of organizations the user belongs to
        # (and other stuff while at it)
        prescriber_orgs.append(membership.organization)
        if membership.organization.pk == prescriber_org_pk:
            org = membership.organization
            matomo_context.update(
                {
                    "account_current_prescriber_org_id": org.pk,
                    "account_sub_type": "prescriber_with_authorized_org"
                    if org.is_authorized
                    else "prescriber_with_unauthorized_org",
                }
            )
            context.update(
                {
                    "current_prescriber_organization": org,
                    "user_is_prescriber_org_admin": membership.is_admin,
                }
            )
    context["user_prescriberorganizations"] = sort_organizations(prescriber_orgs)
    matomo_context["account_organization_ids"] = join_keys_str(context["user_prescriberorganizations"])
    return context, matomo_context


def get_context_institution(user, institution_pk):
    context = {}
    matomo_context = {}
    memberships = (
        user.institutionmembership_set.filter(is_active=True).order_by("created_at").select_related("institution")
    )

    institutions = []
    for membership in memberships:
        # Same as above:
        # In order to avoid an extra SQL query, fetch related institutions
        # and artificially reconstruct the list of institutions the user belongs to
        # (and other stuff while at it)
        institutions.append(membership.institution)
        if membership.institution.pk == institution_pk:
            institution = membership.institution
            matomo_context.update(
                {
                    "account_current_institution_id": institution.pk,
                    "account_sub_type": "inspector_admin" if membership.is_admin else "inspector_not_admin",
                }
            )
            context.update(
                {
                    "current_institution": institution,
                    "user_is_institution_admin": membership.is_admin,
                }
            )

    context["user_institutions"] = sort_organizations(institutions)
    matomo_context["account_institution_ids"] = join_keys_str(context["user_institutions"])
    return context, matomo_context


def user_to_account_type(user):
    if user.is_job_seeker:
        return {
            "account_type": "job_seeker",
            "account_sub_type": "job_seeker_with_peconnect" if user.is_peamu else "job_seeker_without_peconnect",
        }
    elif user.is_siae_staff:
        return {
            "account_type": "employer",
            "account_sub_type": "employer_not_admin",
        }
    elif user.is_prescriber:
        return {
            "account_type": "prescriber",
            "account_sub_type": "prescriber_without_org",
        }
    elif user.is_labor_inspector:
        return {
            "account_type": "labor_inspector",
            "account_sub_type": "inspector_not_admin",
        }

    # especially usual in tests.
    return {
        "account_type": "unknown",
        "account_sub_type": "unknown",
    }
