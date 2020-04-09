from django.test import TestCase

from itou.eligibility.models import AdministrativeCriteria
from itou.siaes.factories import SiaeWithMembershipFactory
from itou.siaes.models import Siae
from itou.users.factories import PrescriberFactory
from itou.www.eligibility_views.forms import AdministrativeCriteriaForm


class AdministrativeCriteriaFormTest(TestCase):
    """
    Test AdministrativeCriteriaForm.
    """

    def test_valid_for_prescriber(self):
        user = PrescriberFactory()
        criterion1 = AdministrativeCriteria.objects.get(pk=13)
        form_data = {f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion1.pk}": "true"}
        form = AdministrativeCriteriaForm(user, siae=None, data=form_data)
        form.is_valid()
        expected_cleaned_data = [criterion1]
        self.assertEqual(form.cleaned_data, expected_cleaned_data)

    def test_valid_for_siae(self):
        siae = SiaeWithMembershipFactory(kind=Siae.KIND_ACI)
        user = siae.members.first()

        criterion1 = AdministrativeCriteria.objects.get(pk=1)
        criterion2 = AdministrativeCriteria.objects.get(pk=5)
        criterion3 = AdministrativeCriteria.objects.get(pk=9)
        criterion4 = AdministrativeCriteria.objects.get(pk=13)

        # At least 1 criterion level 1.
        form_data = {f"{AdministrativeCriteriaForm.LEVEL_1_PREFIX}{criterion1.pk}": "true"}
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        expected_cleaned_data = [criterion1]
        self.assertEqual(form.cleaned_data, expected_cleaned_data)

        # Or at least 3 criterion level 2.
        form_data = {
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion2.pk}": "true",
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion3.pk}": "true",
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion4.pk}": "true",
        }
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        expected_cleaned_data = [criterion2, criterion3, criterion4]
        self.assertEqual(form.cleaned_data, expected_cleaned_data)

    def test_error_criteria_number_for_siae(self):
        """
        Test errors for SIAEs.
        """
        siae = SiaeWithMembershipFactory(kind=Siae.KIND_ACI)
        user = siae.members.first()

        criterion1 = AdministrativeCriteria.objects.get(pk=1)
        criterion2 = AdministrativeCriteria.objects.get(pk=5)
        criterion3 = AdministrativeCriteria.objects.get(pk=9)

        form_data = {f"{AdministrativeCriteriaForm.LEVEL_1_PREFIX}{criterion1.pk}": "false"}
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        self.assertIn(form.ERROR_CRITERIA_NUMBER, form.errors["__all__"])

        form_data = {
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion2.pk}": "true",
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion3.pk}": "true",
        }
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        self.assertIn(form.ERROR_CRITERIA_NUMBER, form.errors["__all__"])

    def test_valid_for_siae_of_kind_etti(self):
        siae = SiaeWithMembershipFactory(kind=Siae.KIND_ETTI)
        user = siae.members.first()

        criterion1 = AdministrativeCriteria.objects.get(pk=1)
        criterion2 = AdministrativeCriteria.objects.get(pk=5)
        criterion3 = AdministrativeCriteria.objects.get(pk=9)

        # At least 1 criterion level 1.
        form_data = {f"{AdministrativeCriteriaForm.LEVEL_1_PREFIX}{criterion1.pk}": "true"}
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        expected_cleaned_data = [criterion1]
        self.assertEqual(form.cleaned_data, expected_cleaned_data)

        # Or at least 2 criterion level 1.
        form_data = {
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion2.pk}": "true",
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion3.pk}": "true",
        }
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        expected_cleaned_data = [criterion2, criterion3]
        self.assertEqual(form.cleaned_data, expected_cleaned_data)

    def test_error_criteria_number_for_siae_of_kind_etti(self):
        """
        Test errors for SIAEs of kind ETTI.
        """
        siae = SiaeWithMembershipFactory(kind=Siae.KIND_ETTI)
        user = siae.members.first()

        criterion1 = AdministrativeCriteria.objects.get(pk=1)
        criterion2 = AdministrativeCriteria.objects.get(pk=5)
        criterion3 = AdministrativeCriteria.objects.get(pk=9)

        # No level 1 criterion.
        form_data = {f"{AdministrativeCriteriaForm.LEVEL_1_PREFIX}{criterion1.pk}": "false"}
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        self.assertIn(form.ERROR_CRITERIA_NUMBER_ETTI, form.errors["__all__"])

        # Only one level 2 criterion.
        form_data = {f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion2.pk}": "true"}
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        self.assertIn(form.ERROR_CRITERIA_NUMBER_ETTI, form.errors["__all__"])

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
        form = AdministrativeCriteriaForm(user, siae=None, data=form_data)
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
        form = AdministrativeCriteriaForm(user, siae=None, data=form_data)
        form.is_valid()
        self.assertIn(form.ERROR_LONG_TERM_JOB_SEEKER, form.errors["__all__"])
