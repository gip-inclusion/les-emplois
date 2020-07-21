from django.test import TestCase

from itou.eligibility.factories import EligibilityDiagnosisFactory, ExpiredEligibilityDiagnosisFactory
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.prescribers.factories import AuthorizedPrescriberOrganizationWithMembershipFactory
from itou.siaes.factories import SiaeWithMembershipFactory
from itou.users.factories import JobSeekerFactory
from itou.utils.perms.user import KIND_PRESCRIBER, KIND_SIAE_STAFF, UserInfo


class EligibilityDiagnosisModelTest(TestCase):
    def test_create_diagnosis(self):
        job_seeker = JobSeekerFactory()
        siae = SiaeWithMembershipFactory()
        user = siae.members.first()
        user_info = UserInfo(
            user=user, kind=KIND_SIAE_STAFF, prescriber_organization=None, is_authorized_prescriber=False, siae=siae
        )

        diagnosis = EligibilityDiagnosis.create_diagnosis(job_seeker, user_info)

        self.assertEqual(diagnosis.job_seeker, job_seeker)
        self.assertEqual(diagnosis.author, user)
        self.assertEqual(diagnosis.author_kind, KIND_SIAE_STAFF)
        self.assertEqual(diagnosis.author_siae, siae)
        self.assertEqual(diagnosis.author_prescriber_organization, None)
        self.assertEqual(diagnosis.administrative_criteria.count(), 0)

    def test_create_diagnosis_with_administrative_criteria(self):

        job_seeker = JobSeekerFactory()
        prescriber_organization = AuthorizedPrescriberOrganizationWithMembershipFactory()
        user = prescriber_organization.members.first()
        user_info = UserInfo(
            user=user,
            kind=KIND_PRESCRIBER,
            prescriber_organization=prescriber_organization,
            is_authorized_prescriber=True,
            siae=None,
        )

        level1 = AdministrativeCriteria.Level.LEVEL_1
        level2 = AdministrativeCriteria.Level.LEVEL_2
        criteria1 = AdministrativeCriteria.objects.get(level=level1, name="Bénéficiaire du RSA")
        criteria2 = AdministrativeCriteria.objects.get(level=level2, name="Niveau d'étude 3 ou infra")
        criteria3 = AdministrativeCriteria.objects.get(level=level2, name="Senior (+50 ans)")

        diagnosis = EligibilityDiagnosis.create_diagnosis(
            job_seeker, user_info, administrative_criteria=[criteria1, criteria2, criteria3]
        )

        self.assertEqual(diagnosis.job_seeker, job_seeker)
        self.assertEqual(diagnosis.author, user)
        self.assertEqual(diagnosis.author_kind, KIND_PRESCRIBER)
        self.assertEqual(diagnosis.author_siae, None)
        self.assertEqual(diagnosis.author_prescriber_organization, prescriber_organization)

        administrative_criteria = diagnosis.administrative_criteria.all()
        self.assertEqual(3, administrative_criteria.count())
        self.assertIn(criteria1, administrative_criteria)
        self.assertIn(criteria2, administrative_criteria)
        self.assertIn(criteria3, administrative_criteria)

    def test_has_expired(self):
        diagnosis = EligibilityDiagnosisFactory()
        self.assertFalse(diagnosis.has_expired)

        self.diagnosis = ExpiredEligibilityDiagnosisFactory()
        self.assertTrue(self.diagnosis.has_expired)


class AdministrativeCriteriaModelTest(TestCase):
    def test_levels_queryset(self):

        level1_criterion = AdministrativeCriteria.objects.filter(level=AdministrativeCriteria.Level.LEVEL_1).first()
        level2_criterion = AdministrativeCriteria.objects.filter(level=AdministrativeCriteria.Level.LEVEL_2).first()

        qs = AdministrativeCriteria.objects.level1()
        self.assertIn(level1_criterion, qs)
        self.assertNotIn(level2_criterion, qs)

        qs = AdministrativeCriteria.objects.level2()
        self.assertIn(level2_criterion, qs)
        self.assertNotIn(level1_criterion, qs)
