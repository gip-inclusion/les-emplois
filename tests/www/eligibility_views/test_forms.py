from itou.companies.enums import CompanyKind
from itou.eligibility.enums import (
    AdministrativeCriteriaKind,
)
from itou.eligibility.models import AdministrativeCriteria
from itou.www.eligibility_views.forms import AdministrativeCriteriaForm
from tests.companies.factories import CompanyFactory


class TestAdministrativeCriteriaForm:
    """
    Test AdministrativeCriteriaForm.
    """

    def test_valid_for_prescriber(self):
        criterion1 = AdministrativeCriteria.objects.get(pk=13)
        form_data = {f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion1.pk}": "true"}
        form = AdministrativeCriteriaForm(is_authorized_prescriber=False, siae=None, data=form_data)
        form.is_valid()
        expected_cleaned_data = [criterion1]
        assert form.cleaned_data == expected_cleaned_data

    def test_valid_for_siae(self):
        company = CompanyFactory(kind=CompanyKind.ACI)

        criterion1 = AdministrativeCriteria.objects.get(pk=1)
        criterion2 = AdministrativeCriteria.objects.get(pk=5)
        criterion3 = AdministrativeCriteria.objects.get(pk=9)
        criterion4 = AdministrativeCriteria.objects.get(pk=13)

        # At least 1 criterion level 1.
        form_data = {f"{criterion1.key}": "true"}
        form = AdministrativeCriteriaForm(is_authorized_prescriber=False, siae=company, data=form_data)
        form.is_valid()
        expected_cleaned_data = [criterion1]
        assert form.cleaned_data == expected_cleaned_data

        # Or at least 3 criterion level 2.
        form_data = {
            f"{criterion2.key}": "true",
            f"{criterion3.key}": "true",
            f"{criterion4.key}": "true",
        }
        form = AdministrativeCriteriaForm(is_authorized_prescriber=False, siae=company, data=form_data)
        form.is_valid()
        expected_cleaned_data = [criterion2, criterion3, criterion4]
        assert form.cleaned_data == expected_cleaned_data

    def test_criteria_fields(self):
        company = CompanyFactory()

        form = AdministrativeCriteriaForm(is_authorized_prescriber=False, siae=company)
        assert AdministrativeCriteria.objects.all().count() == len(form.fields)

    def test_error_criteria_number_for_siae(self):
        """
        Test errors for SIAEs.
        """
        company = CompanyFactory(kind=CompanyKind.ACI)

        criterion1 = AdministrativeCriteria.objects.get(pk=1)
        criterion2 = AdministrativeCriteria.objects.get(pk=5)
        criterion3 = AdministrativeCriteria.objects.get(pk=9)

        form_data = {f"{criterion1.key}": "false"}
        form = AdministrativeCriteriaForm(is_authorized_prescriber=False, siae=company, data=form_data)
        form.is_valid()
        assert form.ERROR_CRITERIA_NUMBER in form.errors["__all__"]

        form_data = {
            f"{criterion2.key}": "true",
            f"{criterion3.key}": "true",
        }
        form = AdministrativeCriteriaForm(is_authorized_prescriber=False, siae=company, data=form_data)
        form.is_valid()
        assert form.ERROR_CRITERIA_NUMBER in form.errors["__all__"]

    def test_valid_for_siae_of_kind_etti(self):
        company = CompanyFactory(kind=CompanyKind.ETTI)

        criterion1 = AdministrativeCriteria.objects.get(pk=1)
        criterion2 = AdministrativeCriteria.objects.get(pk=5)
        criterion3 = AdministrativeCriteria.objects.get(pk=9)

        # At least 1 criterion level 1.
        form_data = {f"{criterion1.key}": "true"}
        form = AdministrativeCriteriaForm(is_authorized_prescriber=False, siae=company, data=form_data)
        form.is_valid()
        expected_cleaned_data = [criterion1]
        assert form.cleaned_data == expected_cleaned_data

        # Or at least 2 criterion level 1.
        form_data = {
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion2.pk}": "true",
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion3.pk}": "true",
        }
        form = AdministrativeCriteriaForm(is_authorized_prescriber=False, siae=company, data=form_data)
        form.is_valid()
        expected_cleaned_data = [criterion2, criterion3]
        assert form.cleaned_data == expected_cleaned_data

    def test_error_criteria_number_for_siae_of_kind_etti(self):
        """
        Test errors for SIAEs of kind ETTI.
        """
        company = CompanyFactory(kind=CompanyKind.ETTI)

        criterion1 = AdministrativeCriteria.objects.get(pk=1)
        criterion2 = AdministrativeCriteria.objects.get(pk=5)

        # No level 1 criterion.
        form_data = {f"{criterion1.key}": "false"}
        form = AdministrativeCriteriaForm(is_authorized_prescriber=False, siae=company, data=form_data)
        form.is_valid()
        assert form.ERROR_CRITERIA_NUMBER_ETTI_AI in form.errors["__all__"]

        # Only one level 2 criterion.
        form_data = {f"{criterion2.key}": "true"}
        form = AdministrativeCriteriaForm(is_authorized_prescriber=False, siae=company, data=form_data)
        form.is_valid()
        assert form.ERROR_CRITERIA_NUMBER_ETTI_AI in form.errors["__all__"]

    def test_error_senior_junior(self):
        """
        Test ERROR_SENIOR_JUNIOR.
        """
        criterion1 = AdministrativeCriteria.objects.get(kind=AdministrativeCriteriaKind.SENIOR)
        criterion2 = AdministrativeCriteria.objects.get(kind=AdministrativeCriteriaKind.JEUNE)

        form_data = {
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion1.pk}": "true",
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion2.pk}": "true",
        }
        form = AdministrativeCriteriaForm(is_authorized_prescriber=False, siae=None, data=form_data)
        form.is_valid()
        assert form.ERROR_SENIOR_JUNIOR in form.errors["__all__"]

    def test_error_error_long_term_job_seeker(self):
        """
        Test ERROR_LONG_TERM_JOB_SEEKER.
        """
        criterion1 = AdministrativeCriteria.objects.get(kind=AdministrativeCriteriaKind.DETLD)
        criterion2 = AdministrativeCriteria.objects.get(kind=AdministrativeCriteriaKind.DELD)

        form_data = {
            # Level 1.
            f"{criterion1.key}": "true",
            # Level 2.
            f"{criterion2.key}": "true",
        }
        form = AdministrativeCriteriaForm(is_authorized_prescriber=False, siae=None, data=form_data)
        form.is_valid()
        assert form.ERROR_LONG_TERM_JOB_SEEKER in form.errors["__all__"]

    def test_no_required_criteria_for_prescriber_with_authorized_organization(self):
        company = CompanyFactory()

        assert not AdministrativeCriteriaForm(is_authorized_prescriber=False, siae=company, data={}).is_valid()
        assert AdministrativeCriteriaForm(is_authorized_prescriber=True, siae=company, data={}).is_valid()

    def test_no_required_criteria_when_no_siae(self):
        company = CompanyFactory()

        assert not AdministrativeCriteriaForm(is_authorized_prescriber=False, siae=company, data={}).is_valid()
        assert AdministrativeCriteriaForm(is_authorized_prescriber=False, siae=None, data={}).is_valid()
