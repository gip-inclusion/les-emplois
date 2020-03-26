from django.test import TestCase

from itou.eligibility.models import AdministrativeCriteria
from itou.users.factories import PrescriberFactory, SiaeStaffFactory
from itou.www.eligibility_views.forms import AdministrativeCriteriaForm


class AdministrativeCriteriaFormTest(TestCase):
    """
    Test AdministrativeCriteriaForm.
    """

    def test_valid_for_prescriber(self):
        user = PrescriberFactory()
        criterion1 = AdministrativeCriteria.objects.get(pk=13)
        form_data = {f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion1.pk}": "true"}
        form = AdministrativeCriteriaForm(user, data=form_data)
        form.is_valid()
        expected_cleaned_data = [criterion1]
        self.assertEqual(form.cleaned_data, expected_cleaned_data)

    def test_valid_for_siae(self):
        user = SiaeStaffFactory()

        criterion1 = AdministrativeCriteria.objects.get(pk=1)
        criterion2 = AdministrativeCriteria.objects.get(pk=3)
        criterion3 = AdministrativeCriteria.objects.get(pk=5)
        criterion4 = AdministrativeCriteria.objects.get(pk=9)
        criterion5 = AdministrativeCriteria.objects.get(pk=13)

        form_data = {
            f"{AdministrativeCriteriaForm.LEVEL_1_PREFIX}{criterion1.pk}": "true",
            f"{AdministrativeCriteriaForm.LEVEL_1_PREFIX}{criterion2.pk}": "true",
        }
        form = AdministrativeCriteriaForm(user, data=form_data)
        form.is_valid()
        expected_cleaned_data = [criterion1, criterion2]
        self.assertEqual(form.cleaned_data, expected_cleaned_data)

        form_data = {
            # Level 1.
            f"{AdministrativeCriteriaForm.LEVEL_1_PREFIX}{criterion1.pk}": "true",
            # Level 2.
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion3.pk}": "true",
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion4.pk}": "true",
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion5.pk}": "true",
        }
        form = AdministrativeCriteriaForm(user, data=form_data)
        form.is_valid()
        expected_cleaned_data = [criterion1, criterion3, criterion4, criterion5]
        self.assertEqual(form.cleaned_data, expected_cleaned_data)

    def test_error_criteria_number_for_siae(self):
        """
        Test ERROR_CRITERIA_NUMBER.
        """
        user = SiaeStaffFactory()

        criterion1 = AdministrativeCriteria.objects.get(pk=1)
        criterion2 = AdministrativeCriteria.objects.get(pk=5)
        criterion3 = AdministrativeCriteria.objects.get(pk=9)

        form_data = {f"{AdministrativeCriteriaForm.LEVEL_1_PREFIX}{criterion1.pk}": "false"}
        form = AdministrativeCriteriaForm(user, data=form_data)
        form.is_valid()
        self.assertIn(form.ERROR_CRITERIA_NUMBER, form.errors["__all__"])

        form_data = {
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion2.pk}": "true",
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion3.pk}": "true",
        }
        form = AdministrativeCriteriaForm(user, data=form_data)
        form.is_valid()
        self.assertIn(form.ERROR_CRITERIA_NUMBER, form.errors["__all__"])

    def test_error_senior_junior(self):
        """
        Test ERROR_SENIOR_JUNIOR.
        """
        user = PrescriberFactory()

        criterion1 = AdministrativeCriteria.objects.get(name="Senior (+50 ans)")
        criterion2 = AdministrativeCriteria.objects.get(name="Jeunes (-26 ans)")

        form_data = {
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion1.pk}": "true",
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion2.pk}": "true",
        }
        form = AdministrativeCriteriaForm(user, data=form_data)
        form.is_valid()
        self.assertIn(form.ERROR_SENIOR_JUNIOR, form.errors["__all__"])

    def test_error_error_long_term_job_seeker(self):
        """
        Test ERROR_LONG_TERM_JOB_SEEKER.
        """
        user = PrescriberFactory()

        criterion1 = AdministrativeCriteria.objects.get(name="DETLD (+ 24 mois)")
        criterion2 = AdministrativeCriteria.objects.get(name="DELD (12-24 mois)")

        form_data = {
            # Level 1.
            f"{AdministrativeCriteriaForm.LEVEL_1_PREFIX}{criterion1.pk}": "true",
            # Level 2.
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion2.pk}": "true",
        }
        form = AdministrativeCriteriaForm(user, data=form_data)
        form.is_valid()
        self.assertIn(form.ERROR_LONG_TERM_JOB_SEEKER, form.errors["__all__"])
