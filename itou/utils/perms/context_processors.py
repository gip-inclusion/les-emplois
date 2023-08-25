from itou.users.enums import IdentityProvider


def sort_organizations(collection):
    return sorted(collection, key=lambda o: (o.kind, o.display_name))


def get_current_organization_and_perms(request):
    if request.user.is_authenticated:
        context, extra_context, extra_matomo_context = {}, {}, {}
        matomo_context = {"is_authenticated": "yes"} | user_to_account_type(request.user)

        if getattr(request, "current_organization", None) is not None:
            if request.user.is_siae_staff:
                extra_context, extra_matomo_context = get_context_siae(request)

            if request.user.is_prescriber:
                extra_context, extra_matomo_context = get_context_prescriber(request)

            if request.user.is_labor_inspector:
                extra_context, extra_matomo_context = get_context_institution(request)

        context.update(extra_context)
        return context | {"matomo_custom_variables": matomo_context | extra_matomo_context}

    return {
        "matomo_custom_variables": {
            "is_authenticated": "no",
            "account_type": "anonymous",
            "account_sub_type": "anonymous",
        }
    }


def get_context_siae(request):
    return (
        # context
        {
            "current_siae": request.current_organization,
            "user_is_siae_admin": request.is_current_organization_admin,
            "user_siaes": sort_organizations(request.organizations),
        },
        # matomo_context
        {
            "account_current_siae_id": request.current_organization.pk,
            "account_sub_type": "employer_admin" if request.is_current_organization_admin else "employer_not_admin",
        },
    )


def get_context_prescriber(request):
    return (
        # context
        {
            "current_prescriber_organization": request.current_organization,
            "user_is_prescriber_org_admin": request.is_current_organization_admin,
            "user_prescriberorganizations": sort_organizations(request.organizations),
        },
        # matomo_context
        {
            "account_current_prescriber_org_id": request.current_organization.pk,
            "account_sub_type": "prescriber_with_authorized_org"
            if request.current_organization.is_authorized
            else "prescriber_with_unauthorized_org",
        },
    )


def get_context_institution(request):
    return (
        # context
        {
            "current_institution": request.current_organization,
            "user_is_institution_admin": request.is_current_organization_admin,
            "user_institutions": sort_organizations(request.organizations),
        },
        # matomo_context
        {
            "account_current_institution_id": request.current_organization.pk,
            "account_sub_type": "inspector_admin" if request.is_current_organization_admin else "inspector_not_admin",
        },
    )


def user_to_account_type(user):
    account_type = user.kind
    if user.is_job_seeker:
        return {
            "account_type": account_type,
            "account_sub_type": (
                "job_seeker_with_peconnect"
                if user.identity_provider == IdentityProvider.PE_CONNECT
                else "job_seeker_without_peconnect"
            ),
        }
    elif user.is_siae_staff:
        return {
            "account_type": account_type,
            "account_sub_type": "employer_not_admin",
        }
    elif user.is_prescriber:
        return {
            "account_type": account_type,
            "account_sub_type": "prescriber_without_org",
        }
    elif user.is_labor_inspector:
        return {
            "account_type": account_type,
            "account_sub_type": "inspector_not_admin",
        }

    # especially usual in tests.
    return {
        "account_type": account_type,
        "account_sub_type": "unknown",
    }
