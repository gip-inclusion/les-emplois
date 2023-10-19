from dateutil.relativedelta import relativedelta
from django.utils import timezone

from itou.companies.enums import CompanyKind
from itou.eligibility.enums import AdministrativeCriteriaLevel
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.www.eligibility_views.forms import AdministrativeCriteriaForm, AdministrativeCriteriaOfJobApplicationForm
from tests.companies.factories import SiaeFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import JobSeekerFactory, PrescriberFactory
from tests.utils.test import TestCase


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
        assert form.cleaned_data == expected_cleaned_data

    def test_valid_for_siae(self):
        siae = SiaeFactory(kind=CompanyKind.ACI, with_membership=True)
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
        assert form.cleaned_data == expected_cleaned_data

        # Or at least 3 criterion level 2.
        form_data = {
            f"{criterion2.key}": "true",
            f"{criterion3.key}": "true",
            f"{criterion4.key}": "true",
        }
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        expected_cleaned_data = [criterion2, criterion3, criterion4]
        assert form.cleaned_data == expected_cleaned_data

    def test_criteria_fields(self):
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()

        form = AdministrativeCriteriaForm(user, siae)
        assert AdministrativeCriteria.objects.all().count() == len(form.fields)

    def test_error_criteria_number_for_siae(self):
        """
        Test errors for SIAEs.
        """
        siae = SiaeFactory(kind=CompanyKind.ACI, with_membership=True)
        user = siae.members.first()

        criterion1 = AdministrativeCriteria.objects.get(pk=1)
        criterion2 = AdministrativeCriteria.objects.get(pk=5)
        criterion3 = AdministrativeCriteria.objects.get(pk=9)

        form_data = {f"{criterion1.key}": "false"}
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        assert form.ERROR_CRITERIA_NUMBER in form.errors["__all__"]

        form_data = {
            f"{criterion2.key}": "true",
            f"{criterion3.key}": "true",
        }
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        assert form.ERROR_CRITERIA_NUMBER in form.errors["__all__"]

    def test_valid_for_siae_of_kind_etti(self):
        siae = SiaeFactory(kind=CompanyKind.ETTI, with_membership=True)
        user = siae.members.first()

        criterion1 = AdministrativeCriteria.objects.get(pk=1)
        criterion2 = AdministrativeCriteria.objects.get(pk=5)
        criterion3 = AdministrativeCriteria.objects.get(pk=9)

        # At least 1 criterion level 1.
        form_data = {f"{criterion1.key}": "true"}
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        expected_cleaned_data = [criterion1]
        assert form.cleaned_data == expected_cleaned_data

        # Or at least 2 criterion level 1.
        form_data = {
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion2.pk}": "true",
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion3.pk}": "true",
        }
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        expected_cleaned_data = [criterion2, criterion3]
        assert form.cleaned_data == expected_cleaned_data

    def test_error_criteria_number_for_siae_of_kind_etti(self):
        """
        Test errors for SIAEs of kind ETTI.
        """
        siae = SiaeFactory(kind=CompanyKind.ETTI, with_membership=True)
        user = siae.members.first()

        criterion1 = AdministrativeCriteria.objects.get(pk=1)
        criterion2 = AdministrativeCriteria.objects.get(pk=5)

        # No level 1 criterion.
        form_data = {f"{criterion1.key}": "false"}
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        assert form.ERROR_CRITERIA_NUMBER_ETTI_AI in form.errors["__all__"]

        # Only one level 2 criterion.
        form_data = {f"{criterion2.key}": "true"}
        form = AdministrativeCriteriaForm(user, siae=siae, data=form_data)
        form.is_valid()
        assert form.ERROR_CRITERIA_NUMBER_ETTI_AI in form.errors["__all__"]

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
        assert form.ERROR_SENIOR_JUNIOR in form.errors["__all__"]

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
        assert form.ERROR_LONG_TERM_JOB_SEEKER in form.errors["__all__"]

    def test_no_required_criteria_for_prescriber_with_authorized_organization(self):
        prescriber = PrescriberFactory()
        authorized_prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
        siae = SiaeFactory()

        assert not AdministrativeCriteriaForm(prescriber, siae, data={}).is_valid()
        assert AdministrativeCriteriaForm(authorized_prescriber, siae, data={}).is_valid()

    def test_no_required_criteria_when_no_siae(self):
        prescriber = PrescriberFactory()
        siae = SiaeFactory()

        assert not AdministrativeCriteriaForm(prescriber, siae, data={}).is_valid()
        assert AdministrativeCriteriaForm(prescriber, None, data={}).is_valid()


class AdministrativeCriteriaOfJobApplicationFormTest(TestCase):
    def test_job_application(self):
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()

        job_seeker = JobSeekerFactory()

        eligibility_diagnosis = EligibilityDiagnosis.create_diagnosis(
            job_seeker,
            author=user,
            author_organization=siae,
            administrative_criteria=[
                AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_1).first()
            ]
            + [AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_2).first()],
        )

        job_application = JobApplicationFactory(
            with_approval=True,
            to_siae=siae,
            sender_siae=siae,
            eligibility_diagnosis=eligibility_diagnosis,
            hiring_start_at=timezone.now() - relativedelta(months=2),
        )

        form = AdministrativeCriteriaOfJobApplicationForm(user, siae, job_application=job_application)

        assert 2 == len(form.fields)
        assert (
            AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_1).first().key
            in form.fields.keys()
        )
        assert (
            AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_2).first().key
            in form.fields.keys()
        )

    def test_num_level2_admin_criteria(self):
        for kind in CompanyKind:
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

                if kind in [CompanyKind.ETTI, CompanyKind.AI]:
                    assert 2 == form.num_level2_admin_criteria
                else:
                    assert 3 == form.num_level2_admin_criteria
