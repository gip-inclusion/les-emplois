from dateutil.relativedelta import relativedelta
from django.test import TestCase
from django.utils import timezone

from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.job_applications.factories import JobApplicationFactory
from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from itou.siaes.enums import SiaeKind
from itou.siaes.factories import SiaeFactory
from itou.users.enums import KIND_SIAE_STAFF
from itou.users.factories import JobSeekerFactory, PrescriberFactory
from itou.utils.perms.user import UserInfo
from itou.www.eligibility_views.forms import AdministrativeCriteriaForm, AdministrativeCriteriaOfJobApplicationForm


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
        siae = SiaeFactory(kind=SiaeKind.ACI, with_membership=True)
        user = siae.members.first()

        criterion1 = AdministrativeCriteria.objects.get(pk=1)
        criterion2 = AdministrativeCriteria.objects.get(pk=5)
        criterion3 = AdministrativeCriteria.objects.get(pk=9)
        criterion4 = AdministrativeCriteria.objects.get(pk=13)

        # At least 1 criterion level 1.
        form_data = {f"{criterion1.key}": "true"}
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        expected_cleaned_data = [criterion1]
        self.assertEqual(form.cleaned_data, expected_cleaned_data)

        # Or at least 3 criterion level 2.
        form_data = {
            f"{criterion2.key}": "true",
            f"{criterion3.key}": "true",
            f"{criterion4.key}": "true",
        }
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        expected_cleaned_data = [criterion2, criterion3, criterion4]
        self.assertEqual(form.cleaned_data, expected_cleaned_data)

    def test_criteria_fields(self):
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()

        form = AdministrativeCriteriaForm(user, siae)
        self.assertEqual(AdministrativeCriteria.objects.all().count(), len(form.fields))

    def test_error_criteria_number_for_siae(self):
        """
        Test errors for SIAEs.
        """
        siae = SiaeFactory(kind=SiaeKind.ACI, with_membership=True)
        user = siae.members.first()

        criterion1 = AdministrativeCriteria.objects.get(pk=1)
        criterion2 = AdministrativeCriteria.objects.get(pk=5)
        criterion3 = AdministrativeCriteria.objects.get(pk=9)

        form_data = {f"{criterion1.key}": "false"}
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        self.assertIn(form.ERROR_CRITERIA_NUMBER, form.errors["__all__"])

        form_data = {
            f"{criterion2.key}": "true",
            f"{criterion3.key}": "true",
        }
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        self.assertIn(form.ERROR_CRITERIA_NUMBER, form.errors["__all__"])

    def test_valid_for_siae_of_kind_etti(self):
        siae = SiaeFactory(kind=SiaeKind.ETTI, with_membership=True)
        user = siae.members.first()

        criterion1 = AdministrativeCriteria.objects.get(pk=1)
        criterion2 = AdministrativeCriteria.objects.get(pk=5)
        criterion3 = AdministrativeCriteria.objects.get(pk=9)

        # At least 1 criterion level 1.
        form_data = {f"{criterion1.key}": "true"}
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
        siae = SiaeFactory(kind=SiaeKind.ETTI, with_membership=True)
        user = siae.members.first()

        criterion1 = AdministrativeCriteria.objects.get(pk=1)
        criterion2 = AdministrativeCriteria.objects.get(pk=5)

        # No level 1 criterion.
        form_data = {f"{criterion1.key}": "false"}
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        self.assertIn(form.ERROR_CRITERIA_NUMBER_ETTI_AI, form.errors["__all__"])

        # Only one level 2 criterion.
        form_data = {f"{criterion2.key}": "true"}
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        self.assertIn(form.ERROR_CRITERIA_NUMBER_ETTI_AI, form.errors["__all__"])

    def test_error_senior_junior(self):
        """
        Test ERROR_SENIOR_JUNIOR.
        """
        user = PrescriberFactory()

        criterion1 = AdministrativeCriteria.objects.get(name="Senior (+50 ans)")
        criterion2 = AdministrativeCriteria.objects.get(name="Jeune (-26 ans)")

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
            f"{criterion1.key}": "true",
            # Level 2.
            f"{criterion2.key}": "true",
        }
        form = AdministrativeCriteriaForm(user, siae=None, data=form_data)
        form.is_valid()
        self.assertIn(form.ERROR_LONG_TERM_JOB_SEEKER, form.errors["__all__"])

    def test_no_required_criteria_for_prescriber_with_authorized_organization(self):
        prescriber = PrescriberFactory()
        authorized_prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
        siae = SiaeFactory()

        self.assertFalse(AdministrativeCriteriaForm(prescriber, siae, data={}).is_valid())
        self.assertTrue(AdministrativeCriteriaForm(authorized_prescriber, siae, data={}).is_valid())

    def test_no_required_criteria_when_no_siae(self):
        prescriber = PrescriberFactory()
        siae = SiaeFactory()

        self.assertFalse(AdministrativeCriteriaForm(prescriber, siae, data={}).is_valid())
        self.assertTrue(AdministrativeCriteriaForm(prescriber, None, data={}).is_valid())


class AdministrativeCriteriaOfJobApplicationFormTest(TestCase):
    def test_job_application(self):
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()

        job_seeker = JobSeekerFactory()

        user_info = UserInfo(
            user=user, kind=KIND_SIAE_STAFF, siae=siae, prescriber_organization=None, is_authorized_prescriber=False
        )

        eligibility_diagnosis = EligibilityDiagnosis.create_diagnosis(
            job_seeker,
            user_info,
            administrative_criteria=[
                AdministrativeCriteria.objects.filter(level=AdministrativeCriteria.Level.LEVEL_1).first()
            ]
            + [AdministrativeCriteria.objects.filter(level=AdministrativeCriteria.Level.LEVEL_2).first()],
        )

        job_application = JobApplicationFactory(
            with_approval=True,
            to_siae=siae,
            sender_siae=siae,
            eligibility_diagnosis=eligibility_diagnosis,
            hiring_start_at=timezone.now() - relativedelta(months=2),
        )

        form = AdministrativeCriteriaOfJobApplicationForm(user, siae, job_application=job_application)
        self.assertEqual(2, len(form.fields))
        self.assertIn(
            AdministrativeCriteria.objects.filter(level=AdministrativeCriteria.Level.LEVEL_1).first().key,
            form.fields.keys(),
        )
        self.assertIn(
            AdministrativeCriteria.objects.filter(level=AdministrativeCriteria.Level.LEVEL_2).first().key,
            form.fields.keys(),
        )

    def test_num_level2_admin_criteria(self):
        for kind in SiaeKind:
            with self.subTest(kind):
                siae = SiaeFactory(kind=kind, with_membership=True)
                user = siae.members.first()

                job_application = JobApplicationFactory(
                    with_approval=True,
                    to_siae=siae,
                    sender_siae=siae,
                    hiring_start_at=timezone.now() - relativedelta(months=2),
                )
                form = AdministrativeCriteriaOfJobApplicationForm(user, siae, job_application=job_application)

                if kind in [SiaeKind.ETTI, SiaeKind.AI]:
                    self.assertEqual(2, form.num_level2_admin_criteria)
                else:
                    self.assertEqual(3, form.num_level2_admin_criteria)
