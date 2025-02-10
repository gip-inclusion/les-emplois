from itou.companies.enums import CompanyKind


class TestCompanyKind:
    def test_siae_choices(self):
        """Ensure that new company kinds are marked as SIAE or not."""
        assert set(CompanyKind.siae_kinds) == set(
            [
                CompanyKind.AI.value,
                CompanyKind.ACI.value,
                CompanyKind.EI.value,
                CompanyKind.EITI.value,
                CompanyKind.ETTI.value,
            ]
        )

        all_company_kind_values = [k[0] for k in CompanyKind.choices]
        assert set(all_company_kind_values).difference(set(CompanyKind.siae_kinds)) == set(
            [
                CompanyKind.EA.value,
                CompanyKind.EATT.value,
                CompanyKind.GEIQ.value,
                CompanyKind.OPCS.value,
            ]
        )
