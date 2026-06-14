from django.db.models import Q

from itou.recommendations import _mock_data
from itou.recommendations.enums import ProfileFlag
from itou.recommendations.models import Beneficiary
from itou.www.recommendations.enums import BeneficiaryOrder


_ORDER_BY = {
    BeneficiaryOrder.FULL_NAME_ASC: ("last_name", "first_name", "pk"),
    BeneficiaryOrder.FULL_NAME_DESC: ("-last_name", "-first_name", "-pk"),
}

_CRITERIA_ORDER = (
    ProfileFlag.RSA,
    ProfileFlag.DELD,
    ProfileFlag.DETLD,
    ProfileFlag.JEUNE,
    ProfileFlag.SENIOR,
    ProfileFlag.QPV,
    ProfileFlag.ZRR,
    ProfileFlag.OETH,
)


def get_beneficiaries_qs(*, user, organization):
    return Beneficiary.objects.filter(
        referent_email=user.email,
        organization_safir=organization.code_safir_pole_emploi,
    )


def get_beneficiaries_for_user(
    *,
    user,
    organization,
    order=BeneficiaryOrder.FULL_NAME_ASC,
    # FIXME llalba: profile_flags should be used to filter the queryset
    profile_kinds=None,
    beneficiary=None,
):
    qs = get_beneficiaries_qs(user=user, organization=organization).order_by(*_ORDER_BY[order])
    if beneficiary is not None:
        qs = qs.filter(pk=beneficiary.pk)
    beneficiaries = list(qs)
    return beneficiaries


def get_beneficiary_for_user(*, public_id, user, organization):
    return get_beneficiaries_qs(user=user, organization=organization).filter(public_id=public_id).first()


def beneficiary_autocomplete_search(
    *,
    user,
    organization,
    term,
    limit=20,
):
    term = term.strip()
    if not term:
        return []
    qs = get_beneficiaries_qs(user=user, organization=organization)
    term_q = Q(
        *(Q(first_name__unaccent__icontains=bit) | Q(last_name__unaccent__icontains=bit) for bit in term.split()),
        _connector=Q.AND,
    )
    return list(qs.filter(term_q).order_by("last_name", "first_name")[:limit])


def profile_flags(beneficiary):
    # FIXME llalba: hardcoded
    return {flag.value: True for flag in ProfileFlag}


def profile_criteria_labels(flags):
    """List of criteria labels, in a deterministic order, for which the given flags are truthy."""
    return [flag.label for flag in _CRITERIA_ORDER if flags.get(flag.value)]


def beneficiary_diagnostic_for(*, beneficiary):
    # FIXME llalba: hardcoded
    return _mock_data.HARDCODED_DIAGNOSIS


def recommendations_for(*, beneficiary, filters=None):
    # FIXME llalba: hardcoded
    return _mock_data.HARDCODED_RECOMMENDATIONS


def map_points_for(recommendations):
    """Flatten the recommendations into the marker list consumed by the OpenLayers map."""
    return [
        {
            "name": provider["name"],
            "kind_label": item["kind_label"],
            "address": provider["address"],
            "lat": provider["lat"],
            "lon": provider["lon"],
        }
        for item in recommendations
        for provider in item["providers"]
        if provider["show_map"]
    ]
