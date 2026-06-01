import pytest
from django.core.exceptions import ValidationError

from itou.recommendations.models import Beneficiary
from tests.recommendations.factories import BeneficiaryFactory


class TestBeneficiaryFranceTravailIdValidator:
    def test_accepts_11_digits(self):
        BeneficiaryFactory.build(for_snapshot=True, france_travail_id="12345678901").full_clean()

    def test_blank_is_not_valid(self):
        with pytest.raises(ValidationError) as exc:
            BeneficiaryFactory.build(for_snapshot=True, france_travail_id="").full_clean()
        assert "france_travail_id" in exc.value.error_dict

    @pytest.mark.parametrize("bad", ["1234567890", "123456789012", "1"])
    def test_rejects_wrong_length(self, bad):
        with pytest.raises(ValidationError) as exc:
            BeneficiaryFactory.build(for_snapshot=True, france_travail_id=bad).full_clean()
        assert "france_travail_id" in exc.value.error_dict

    def test_rejects_non_digits(self):
        with pytest.raises(ValidationError) as exc:
            BeneficiaryFactory.build(for_snapshot=True, france_travail_id="abcdefghijk").full_clean()
        assert "france_travail_id" in exc.value.error_dict


class TestBeneficiaryOrganizationSafirValidator:
    def test_accepts_5_digits(self):
        BeneficiaryFactory.build(for_snapshot=True, organization_safir="12345").full_clean()

    @pytest.mark.parametrize("bad", ["1234", "123456", ""])
    def test_rejects_wrong_length(self, bad):
        with pytest.raises(ValidationError) as exc:
            BeneficiaryFactory.build(for_snapshot=True, organization_safir=bad).full_clean()
        assert "organization_safir" in exc.value.error_dict

    def test_rejects_non_digits(self):
        with pytest.raises(ValidationError) as exc:
            BeneficiaryFactory.build(for_snapshot=True, organization_safir="ABCDE").full_clean()
        assert "organization_safir" in exc.value.error_dict


class TestReferentEmailCaseInsensitive:
    def test_filter_matches_across_cases(self):
        BeneficiaryFactory(referent_email="Foo@Example.COM")
        assert Beneficiary.objects.filter(referent_email="foo@example.com").exists()
        assert Beneficiary.objects.filter(referent_email="FOO@EXAMPLE.COM").exists()
        assert Beneficiary.objects.filter(referent_email="foo@example.com").count() == 1

    def test_filter_misses_a_different_local_part(self):
        BeneficiaryFactory(referent_email="foo@example.com")
        assert not Beneficiary.objects.filter(referent_email="bar@example.com").exists()
