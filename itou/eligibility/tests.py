import datetime

from dateutil.relativedelta import relativedelta
from django.test import TestCase
from django.utils import timezone

from itou.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory
from itou.eligibility.factories import (
    EligibilityDiagnosisFactory,
    EligibilityDiagnosisMadeBySiaeFactory,
    ExpiredEligibilityDiagnosisFactory,
    ExpiredEligibilityDiagnosisMadeBySiaeFactory,
)
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.prescribers.factories import AuthorizedPrescriberOrganizationWithMembershipFactory
from itou.siaes.factories import SiaeWithMembershipFactory
from itou.users.factories import JobSeekerFactory
from itou.utils.perms.user import KIND_PRESCRIBER, KIND_SIAE_STAFF, UserInfo


class EligibilityDiagnosisQuerySetTest(TestCase):
    """
    Test EligibilityDiagnosisQuerySet.
    """

    def test_valid(self):
        expected_num = 5
        EligibilityDiagnosisFactory.create_batch(expected_num)
        ExpiredEligibilityDiagnosisFactory.create_batch(expected_num)
        self.assertEqual(expected_num * 2, EligibilityDiagnosis.objects.all().count())
        self.assertEqual(expected_num, EligibilityDiagnosis.objects.valid().count())

    def test_expired(self):
        expected_num = 3
        EligibilityDiagnosisFactory.create_batch(expected_num)
        ExpiredEligibilityDiagnosisFactory.create_batch(expected_num)
        self.assertEqual(expected_num * 2, EligibilityDiagnosis.objects.all().count())
        self.assertEqual(expected_num, EligibilityDiagnosis.objects.expired().count())


class EligibilityDiagnosisManagerTest(TestCase):
    """
    Test EligibilityDiagnosisManager.
    """

    def test_valid_and_expired_methods(self):
        """
        Test both `has_considered_valid()`, `last_considered_valid()` and `last_expired()` methods.
        """

        # No diagnosis.
        job_seeker = JobSeekerFactory()
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(job_seeker=job_seeker)
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=job_seeker)
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=job_seeker)
        self.assertIsNone(last_considered_valid)
        self.assertIsNone(last_expired)
        self.assertFalse(has_considered_valid)

        # Has Itou diagnosis.
        diagnosis = EligibilityDiagnosisFactory()
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(job_seeker=diagnosis.job_seeker)
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=diagnosis.job_seeker)
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=diagnosis.job_seeker)
        self.assertEqual(last_considered_valid, diagnosis)
        self.assertIsNone(last_expired)
        self.assertTrue(has_considered_valid)

        # Has a valid PASS IAE but NO diagnosis.
        approval = ApprovalFactory()
        job_seeker = approval.user
        self.assertEqual(0, job_seeker.eligibility_diagnoses.count())
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(job_seeker=job_seeker)
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=job_seeker)
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=job_seeker)
        self.assertTrue(has_considered_valid)
        self.assertIsNone(last_considered_valid)
        self.assertIsNone(last_expired)

        # Has valid Pôle emploi diagnosis.
        job_seeker = JobSeekerFactory()
        PoleEmploiApprovalFactory(pole_emploi_id=job_seeker.pole_emploi_id, birthdate=job_seeker.birthdate)
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(job_seeker=job_seeker)
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=job_seeker)
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=job_seeker)
        self.assertTrue(has_considered_valid)
        self.assertIsNone(last_considered_valid)
        self.assertIsNone(last_expired)

        # Has expired Pôle emploi diagnosis.
        job_seeker = JobSeekerFactory()
        end_at = datetime.date.today() - relativedelta(years=2)
        start_at = end_at - relativedelta(years=2)
        PoleEmploiApprovalFactory(
            pole_emploi_id=job_seeker.pole_emploi_id, birthdate=job_seeker.birthdate, start_at=start_at, end_at=end_at
        )
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(job_seeker=job_seeker)
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=job_seeker)
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=job_seeker)
        self.assertFalse(has_considered_valid)
        self.assertIsNone(last_considered_valid)
        self.assertIsNone(last_expired)

        # Has expired Itou diagnosis.
        expired_diagnosis = ExpiredEligibilityDiagnosisFactory()
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(
            job_seeker=expired_diagnosis.job_seeker
        )
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(
            job_seeker=expired_diagnosis.job_seeker
        )
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=expired_diagnosis.job_seeker)
        self.assertFalse(has_considered_valid)
        self.assertIsNone(last_considered_valid)
        self.assertIsNotNone(last_expired)

        # Has expired Itou diagnosis but has an ongoing PASS IAE.
        expired_diagnosis = ExpiredEligibilityDiagnosisFactory()
        ApprovalFactory(user=expired_diagnosis.job_seeker)
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(
            job_seeker=expired_diagnosis.job_seeker
        )
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(
            job_seeker=expired_diagnosis.job_seeker
        )
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=expired_diagnosis.job_seeker)

        self.assertTrue(has_considered_valid)
        self.assertEqual(last_considered_valid, expired_diagnosis)
        self.assertIsNone(last_expired)

        # Has Itou diagnosis made by an SIAE.
        siae1 = SiaeWithMembershipFactory()
        siae2 = SiaeWithMembershipFactory()
        diagnosis = EligibilityDiagnosisMadeBySiaeFactory(author_siae=siae1)
        # From `siae1` perspective.
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(
            job_seeker=diagnosis.job_seeker, for_siae=siae1
        )
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(
            job_seeker=diagnosis.job_seeker, for_siae=siae1
        )
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=diagnosis.job_seeker, for_siae=siae1)
        self.assertTrue(has_considered_valid)
        self.assertEqual(last_considered_valid, diagnosis)
        self.assertIsNone(last_expired)
        # From `siae2` perspective.
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(
            job_seeker=diagnosis.job_seeker, for_siae=siae2
        )
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(
            job_seeker=diagnosis.job_seeker, for_siae=siae2
        )
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=diagnosis.job_seeker, for_siae=siae2)
        self.assertFalse(has_considered_valid)
        self.assertIsNone(last_considered_valid)
        self.assertIsNone(last_expired)

        # Has Itou diagnosis made by a prescriber.
        siae = SiaeWithMembershipFactory()
        prescriber_diagnosis = EligibilityDiagnosisFactory()
        # From siae perspective.
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(
            job_seeker=prescriber_diagnosis.job_seeker, for_siae=siae
        )
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(
            job_seeker=prescriber_diagnosis.job_seeker, for_siae=siae
        )
        last_expired = EligibilityDiagnosis.objects.last_expired(
            job_seeker=prescriber_diagnosis.job_seeker, for_siae=siae
        )
        self.assertTrue(has_considered_valid)
        self.assertEqual(last_considered_valid, prescriber_diagnosis)
        self.assertIsNone(last_expired)

        # Has 2 Itou diagnoses: 1 made by an SIAE prior to another one by a prescriber.
        job_seeker = JobSeekerFactory()
        siae = SiaeWithMembershipFactory()
        prescriber_diagnosis = EligibilityDiagnosisFactory(job_seeker=job_seeker)
        # From `siae` perspective.
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(job_seeker=job_seeker, for_siae=siae)
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(
            job_seeker=job_seeker, for_siae=siae
        )
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=job_seeker, for_siae=siae)
        self.assertTrue(has_considered_valid)
        # A diagnosis made by a prescriber takes precedence.
        self.assertEqual(last_considered_valid, prescriber_diagnosis)
        self.assertIsNone(last_expired)

        # Has an expired Itou diagnoses made by another SIAE.
        job_seeker = JobSeekerFactory()
        siae1 = SiaeWithMembershipFactory()
        siae2 = SiaeWithMembershipFactory()
        expired_diagnosis = ExpiredEligibilityDiagnosisMadeBySiaeFactory(job_seeker=job_seeker, author_siae=siae1)

        # From `siae` perspective.
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=job_seeker, for_siae=siae1)
        self.assertEqual(last_expired, expired_diagnosis)
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=job_seeker, for_siae=siae2)
        self.assertIsNone(last_expired)

        # Has 2 Itou diagnoses: 1 is considered expired and the second is considered valid.
        job_seeker = JobSeekerFactory()
        ExpiredEligibilityDiagnosisFactory(job_seeker=job_seeker)
        EligibilityDiagnosisFactory(job_seeker=job_seeker)

        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=job_seeker)
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=job_seeker)
        # When has a valid diagnosis, `last_expired` return None
        self.assertIsNotNone(last_considered_valid)
        self.assertIsNone(last_expired)

        # Has 2 Itou diagnoses expired: the last one expired must be returned.
        job_seeker = JobSeekerFactory()

        date_6m = (
            timezone.now() - relativedelta(months=EligibilityDiagnosis.EXPIRATION_DELAY_MONTHS) - relativedelta(day=1)
        )
        date_12m = date_6m - relativedelta(months=6)

        expired_diagnosis_old = EligibilityDiagnosisFactory(job_seeker=job_seeker, created_at=date_12m)
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=job_seeker)
        self.assertEqual(last_expired, expired_diagnosis_old)

        expired_diagnosis_last = EligibilityDiagnosisFactory(job_seeker=job_seeker, created_at=date_6m)
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=job_seeker)
        self.assertEqual(last_expired, expired_diagnosis_last)


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
        criteria2 = AdministrativeCriteria.objects.get(level=level2, name="Niveau d'étude 3 (CAP, BEP) ou infra")
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

    def test_is_valid(self):
        # Valid diagnosis.
        diagnosis = EligibilityDiagnosisFactory()
        self.assertTrue(diagnosis.is_valid)

        # Expired diagnosis.
        diagnosis = ExpiredEligibilityDiagnosisFactory()
        self.assertFalse(diagnosis.is_valid)

    def test_is_considered_valid(self):
        # Valid diagnosis.
        diagnosis = EligibilityDiagnosisFactory()
        self.assertTrue(diagnosis.is_considered_valid)

        # Expired diagnosis.
        diagnosis = ExpiredEligibilityDiagnosisFactory()
        self.assertFalse(diagnosis.is_considered_valid)

        # Expired diagnosis but ongoing PASS IAE.
        diagnosis = ExpiredEligibilityDiagnosisFactory()
        ApprovalFactory(user=diagnosis.job_seeker)
        self.assertTrue(diagnosis.is_considered_valid)


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

    def test_key_property(self):
        criterion_level_1 = AdministrativeCriteria.objects.filter(level=AdministrativeCriteria.Level.LEVEL_1).first()
        self.assertEqual(criterion_level_1.key, f"level_{criterion_level_1.level}_{criterion_level_1.pk}")

        criterion_level_2 = AdministrativeCriteria.objects.filter(level=AdministrativeCriteria.Level.LEVEL_2).first()
        self.assertEqual(criterion_level_2.key, f"level_{criterion_level_2.level}_{criterion_level_2.pk}")
