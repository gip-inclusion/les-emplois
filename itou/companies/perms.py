from itou.companies.enums import CompanyKind


def can_create_antenna(request):
    """
    Only admin employers can create an antenna for their SIAE.

    For SIAE structures (AI, ACI...) the convention has to be present to link the parent SIAE and its antenna.
    In some edge cases (e.g. SIAE created by staff and not yet officialized) the convention is absent,
    in that case we must absolutely not allow any antenna to be created.

    For non SIAE structures (EA, EATT...) the convention logic is not implemented thus no convention ever exists.
    Antennas cannot be freely created by the user as the EA system authorities do not allow any non official SIRET
    to be used (except for GEIQ).

    Finally, for OPCS it has been decided for now to disallow it; those structures are strongly attached to
    a given territory and thus would not need to join others.
    """
    return bool(
        request.user.is_employer
        and request.is_current_organization_admin
        and request.current_organization.kind in [CompanyKind.GEIQ, *CompanyKind.siae_kinds()]
        and request.current_organization.is_active
    )
