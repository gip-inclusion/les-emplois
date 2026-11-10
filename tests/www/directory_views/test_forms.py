from itou.companies.enums import CompanyKind
from itou.prescribers.enums import PrescriberOrganizationKind


def test_company_kind_choices_are_disjoint_from_prescriber_organization_kind_choices():
    assert not set(CompanyKind) & set(PrescriberOrganizationKind)
