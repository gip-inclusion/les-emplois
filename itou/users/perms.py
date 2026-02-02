from itou.users.enums import IdentityProvider


def can_prefill_orientation_on_dora(request):
    # Authorized prescribers can_view_personal_information, always.
    # Be sure to change the calling code if allowing other professionals.
    return bool(
        request.user.is_authenticated
        # Required for auto login.
        and request.user.identity_provider == IdentityProvider.PRO_CONNECT
        # An authorized organization is validated through a manual process.
        # Prevents taking over a DORA organization by registering a DORA SIRET
        # for a not-yet registered organization on Les Emplois.
        and request.from_authorized_prescriber
        and request.current_organization.siret
    )
