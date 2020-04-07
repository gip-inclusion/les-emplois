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
        form = AdministrativeCriteriaForm(user, data=form_data)
        form.is_valid()
        expected_cleaned_data = [criterion1]
        self.assertEqual(form.cleaned_data, expected_cleaned_data)

    def test_valid_for_siae(self):
        siae = SiaeWithMembershipFactory(kind=Siae.KIND_ACI)
        user = siae.members.first()

        criterion1 = AdministrativeCriteria.objects.get(pk=1)
        criterion2 = AdministrativeCriteria.objects.get(pk=3)
        criterion3 = AdministrativeCriteria.objects.get(pk=5)
        criterion4 = AdministrativeCriteria.objects.get(pk=9)
        criterion5 = AdministrativeCriteria.objects.get(pk=13)

        form_data = {
            f"{AdministrativeCriteriaForm.LEVEL_1_PREFIX}{criterion1.pk}": "true",
            f"{AdministrativeCriteriaForm.LEVEL_1_PREFIX}{criterion2.pk}": "true",
        }
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
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
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        expected_cleaned_data = [criterion1, criterion3, criterion4, criterion5]
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

        # Level 1.
        criterion1 = AdministrativeCriteria.objects.get(
            name="Bénéficiaire du RSA", level=AdministrativeCriteria.Level.LEVEL_1
        )
        # Level 2 (one required).
        criterion2 = AdministrativeCriteria.objects.get(
            name="Sortant de l'ASE", level=AdministrativeCriteria.Level.LEVEL_2
        )
        # Level 2 (three required).
        criterion3 = AdministrativeCriteria.objects.get(
            name="Niveau d'étude 3 ou infra", level=AdministrativeCriteria.Level.LEVEL_2
        )
        criterion4 = AdministrativeCriteria.objects.get(
            name="Jeunes (-26 ans)", level=AdministrativeCriteria.Level.LEVEL_2
        )
        criterion5 = AdministrativeCriteria.objects.get(
            name="Parent isolé", level=AdministrativeCriteria.Level.LEVEL_2
        )

        form_data = {f"{AdministrativeCriteriaForm.LEVEL_1_PREFIX}{criterion1.pk}": "true"}
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        expected_cleaned_data = [criterion1]
        self.assertEqual(form.cleaned_data, expected_cleaned_data)

        form_data = {f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion2.pk}": "true"}
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        expected_cleaned_data = [criterion2]
        self.assertEqual(form.cleaned_data, expected_cleaned_data)

        form_data = {
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion3.pk}": "true",
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion4.pk}": "true",
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion5.pk}": "true",
        }
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        expected_cleaned_data = [criterion3, criterion4, criterion5]
        self.assertEqual(form.cleaned_data, expected_cleaned_data)

    def test_error_criteria_number_for_siae_of_kind_etti(self):
        """
        Test errors for SIAEs of kind ETTI.
        """
        siae = SiaeWithMembershipFactory(kind=Siae.KIND_ETTI)
        user = siae.members.first()

        # Level 1.
        criterion1 = AdministrativeCriteria.objects.get(
            name="Bénéficiaire du RSA", level=AdministrativeCriteria.Level.LEVEL_1
        )
        # Level 2 (one required).
        criterion2 = AdministrativeCriteria.objects.get(
            name="Sortant de l'ASE", level=AdministrativeCriteria.Level.LEVEL_2
        )
        # Level 2 (three required).
        criterion3 = AdministrativeCriteria.objects.get(
            name="Niveau d'étude 3 ou infra", level=AdministrativeCriteria.Level.LEVEL_2
        )
        criterion4 = AdministrativeCriteria.objects.get(
            name="Jeunes (-26 ans)", level=AdministrativeCriteria.Level.LEVEL_2
        )

        form_data = {f"{AdministrativeCriteriaForm.LEVEL_1_PREFIX}{criterion1.pk}": "false"}
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        self.assertIn(form.ERROR_CRITERIA_NUMBER_ETTI, form.errors["__all__"])

        form_data = {f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion2.pk}": "false"}
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        self.assertIn(form.ERROR_CRITERIA_NUMBER_ETTI, form.errors["__all__"])

        form_data = {
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion3.pk}": "true",
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion4.pk}": "true",
        }
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
