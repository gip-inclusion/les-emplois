from itou.companies.enums import CompanyKind


def test_siae_kinds():
    """Ensure that new company kinds are marked as SIAE or not."""
    assert set(CompanyKind.siae_kinds()) == {
        CompanyKind.AI.value,
        CompanyKind.ACI.value,
        CompanyKind.EI.value,
        CompanyKind.EITI.value,
        CompanyKind.ETTI.value,
    }

    assert set(CompanyKind.values) - set(CompanyKind.siae_kinds()) == {
        CompanyKind.EA.value,
        CompanyKind.EATT.value,
        CompanyKind.GEIQ.value,
        CompanyKind.OPCS.value,
    }
