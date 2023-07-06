import datetime

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from itou.eligibility.enums import AdministrativeCriteriaLevel, AuthorKind
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.eligibility.models.common import AdministrativeCriteriaQuerySet
from itou.utils.perms.user import UserInfo
from tests.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory
from tests.eligibility.factories import (
    EligibilityDiagnosisFactory,
    EligibilityDiagnosisMadeBySiaeFactory,
    ExpiredEligibilityDiagnosisFactory,
    ExpiredEligibilityDiagnosisMadeBySiaeFactory,
)
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.siaes.factories import SiaeFactory
from tests.users.factories import JobSeekerFactory
from tests.utils.test import TestCase


class EligibilityDiagnosisQuerySetTest(TestCase):
    """
    Test EligibilityDiagnosisQuerySet.
    """

    def test_valid(self):
        expected_num = 5
        EligibilityDiagnosisFactory.create_batch(expected_num)
        ExpiredEligibilityDiagnosisFactory.create_batch(expected_num)
        assert expected_num * 2 == EligibilityDiagnosis.objects.all().count()
        assert expected_num == EligibilityDiagnosis.objects.valid().count()

    def test_expired(self):
        expected_num = 3
        EligibilityDiagnosisFactory.create_batch(expected_num)
        ExpiredEligibilityDiagnosisFactory.create_batch(expected_num)
        assert expected_num * 2 == EligibilityDiagnosis.objects.all().count()
        assert expected_num == EligibilityDiagnosis.objects.expired().count()


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
        assert last_considered_valid is None
        assert last_expired is None
        assert not has_considered_valid

        # Has Itou diagnosis.
        diagnosis = EligibilityDiagnosisFactory()
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(job_seeker=diagnosis.job_seeker)
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=diagnosis.job_seeker)
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=diagnosis.job_seeker)
        assert last_considered_valid == diagnosis
        assert last_expired is None
        assert has_considered_valid

        # Has a valid PASS IAE but NO diagnosis.
        approval = ApprovalFactory(eligibility_diagnosis=None)
        job_seeker = approval.user
        assert 0 == job_seeker.eligibility_diagnoses.count()
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(job_seeker=job_seeker)
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=job_seeker)
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=job_seeker)
        assert has_considered_valid
        assert last_considered_valid is None
        assert last_expired is None

        # Has valid Pôle emploi diagnosis.
        job_seeker = JobSeekerFactory()
        PoleEmploiApprovalFactory(pole_emploi_id=job_seeker.pole_emploi_id, birthdate=job_seeker.birthdate)
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(job_seeker=job_seeker)
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=job_seeker)
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=job_seeker)
        assert has_considered_valid
        assert last_considered_valid is None
        assert last_expired is None

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
        assert not has_considered_valid
        assert last_considered_valid is None
        assert last_expired is None

        # Has expired Itou diagnosis.
        expired_diagnosis = ExpiredEligibilityDiagnosisFactory()
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(
            job_seeker=expired_diagnosis.job_seeker
        )
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(
            job_seeker=expired_diagnosis.job_seeker
        )
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=expired_diagnosis.job_seeker)
        assert not has_considered_valid
        assert last_considered_valid is None
        assert last_expired is not None

        # Has expired Itou diagnosis but has an ongoing PASS IAE.
        expired_diagnosis = ExpiredEligibilityDiagnosisFactory()
        ApprovalFactory(user=expired_diagnosis.job_seeker, eligibility_diagnosis=expired_diagnosis)
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(
            job_seeker=expired_diagnosis.job_seeker
        )
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(
            job_seeker=expired_diagnosis.job_seeker
        )
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=expired_diagnosis.job_seeker)

        assert has_considered_valid
        assert last_considered_valid == expired_diagnosis
        assert last_expired is None

        # Has Itou diagnosis made by an SIAE.
        siae1 = SiaeFactory(with_membership=True)
        siae2 = SiaeFactory(with_membership=True)
        diagnosis = EligibilityDiagnosisMadeBySiaeFactory(author_siae=siae1)
        # From `siae1` perspective.
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(
            job_seeker=diagnosis.job_seeker, for_siae=siae1
        )
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(
            job_seeker=diagnosis.job_seeker, for_siae=siae1
        )
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=diagnosis.job_seeker, for_siae=siae1)
        assert has_considered_valid
        assert last_considered_valid == diagnosis
        assert last_expired is None
        # From `siae2` perspective.
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(
            job_seeker=diagnosis.job_seeker, for_siae=siae2
        )
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(
            job_seeker=diagnosis.job_seeker, for_siae=siae2
        )
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=diagnosis.job_seeker, for_siae=siae2)
        assert not has_considered_valid
        assert last_considered_valid is None
        assert last_expired is None

        # Has Itou diagnosis made by a prescriber.
        siae = SiaeFactory(with_membership=True)
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
        assert has_considered_valid
        assert last_considered_valid == prescriber_diagnosis
        assert last_expired is None

        # Has 2 Itou diagnoses: 1 made by an SIAE prior to another one by a prescriber.
        job_seeker = JobSeekerFactory()
        siae = SiaeFactory(with_membership=True)
        prescriber_diagnosis = EligibilityDiagnosisFactory(job_seeker=job_seeker)
        # From `siae` perspective.
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(job_seeker=job_seeker, for_siae=siae)
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(
            job_seeker=job_seeker, for_siae=siae
        )
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=job_seeker, for_siae=siae)
        assert has_considered_valid
        # A diagnosis made by a prescriber takes precedence.
        assert last_considered_valid == prescriber_diagnosis
        assert last_expired is None

        # Has an expired Itou diagnoses made by another SIAE.
        job_seeker = JobSeekerFactory()
        siae1 = SiaeFactory(with_membership=True)
        siae2 = SiaeFactory(with_membership=True)
        expired_diagnosis = ExpiredEligibilityDiagnosisMadeBySiaeFactory(job_seeker=job_seeker, author_siae=siae1)

        # From `siae` perspective.
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=job_seeker, for_siae=siae1)
        assert last_expired == expired_diagnosis
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=job_seeker, for_siae=siae2)
        assert last_expired is None

        # Has 2 Itou diagnoses: 1 is considered expired and the second is considered valid.
        job_seeker = JobSeekerFactory()
        ExpiredEligibilityDiagnosisFactory(job_seeker=job_seeker)
        EligibilityDiagnosisFactory(job_seeker=job_seeker)

        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=job_seeker)
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=job_seeker)
        # When has a valid diagnosis, `last_expired` return None
        assert last_considered_valid is not None
        assert last_expired is None

        # Has 2 Itou diagnoses expired: the last one expired must be returned.
        job_seeker = JobSeekerFactory()

        date_6m = (
            timezone.now() - relativedelta(months=EligibilityDiagnosis.EXPIRATION_DELAY_MONTHS) - relativedelta(day=1)
        )
        date_12m = date_6m - relativedelta(months=6)

        expired_diagnosis_old = EligibilityDiagnosisFactory(job_seeker=job_seeker, created_at=date_12m)
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=job_seeker)
        assert last_expired == expired_diagnosis_old

        expired_diagnosis_last = EligibilityDiagnosisFactory(job_seeker=job_seeker, created_at=date_6m)
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=job_seeker)
        assert last_expired == expired_diagnosis_last


class EligibilityDiagnosisModelTest(TestCase):
    def test_create_diagnosis(self):
        job_seeker = JobSeekerFactory()
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()
        user_info = UserInfo(
            user=user,
            kind=AuthorKind.SIAE_STAFF,
            prescriber_organization=None,
            is_authorized_prescriber=False,
            siae=siae,
        )

        diagnosis = EligibilityDiagnosis.create_diagnosis(job_seeker, user_info)

        assert diagnosis.job_seeker == job_seeker
        assert diagnosis.author == user
        assert diagnosis.author_kind == AuthorKind.SIAE_STAFF
        assert diagnosis.author_siae == siae
        assert diagnosis.author_prescriber_organization is None
        assert diagnosis.administrative_criteria.count() == 0

    def test_create_diagnosis_with_administrative_criteria(self):

        job_seeker = JobSeekerFactory()
        prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
        user = prescriber_organization.members.first()
        user_info = UserInfo(
            user=user,
            kind=AuthorKind.PRESCRIBER,
            prescriber_organization=prescriber_organization,
            is_authorized_prescriber=True,
            siae=None,
        )

        level1 = AdministrativeCriteriaLevel.LEVEL_1
        level2 = AdministrativeCriteriaLevel.LEVEL_2
        criteria1 = AdministrativeCriteria.objects.get(level=level1, name="Bénéficiaire du RSA")
        criteria2 = AdministrativeCriteria.objects.get(level=level2, name="Niveau d'étude 3 (CAP, BEP) ou infra")
        criteria3 = AdministrativeCriteria.objects.get(level=level2, name="Senior (+50 ans)")

        diagnosis = EligibilityDiagnosis.create_diagnosis(
            job_seeker, user_info, administrative_criteria=[criteria1, criteria2, criteria3]
        )

        assert diagnosis.job_seeker == job_seeker
        assert diagnosis.author == user
        assert diagnosis.author_kind == AuthorKind.PRESCRIBER
        assert diagnosis.author_siae is None
        assert diagnosis.author_prescriber_organization == prescriber_organization

        administrative_criteria = diagnosis.administrative_criteria.all()
        assert 3 == administrative_criteria.count()
        assert criteria1 in administrative_criteria
        assert criteria2 in administrative_criteria
        assert criteria3 in administrative_criteria

    def test_update_diagnosis(self):
        siae = SiaeFactory(with_membership=True)
        user_info = UserInfo(
            user=siae.members.first(),
            kind=AuthorKind.SIAE_STAFF,
            prescriber_organization=None,
            is_authorized_prescriber=False,
            siae=siae,
        )

        current_diagnosis = EligibilityDiagnosisFactory()
        new_diagnosis = EligibilityDiagnosis.update_diagnosis(current_diagnosis, user_info, [])
        current_diagnosis.refresh_from_db()

        # Some information should be copied...
        assert new_diagnosis.job_seeker == current_diagnosis.job_seeker
        # ... or updated.
        assert new_diagnosis.author == user_info.user
        assert new_diagnosis.author_kind == AuthorKind.SIAE_STAFF
        assert new_diagnosis.author_siae == siae
        assert new_diagnosis.author_prescriber_organization is None
        assert new_diagnosis.administrative_criteria.count() == 0

        # And the old diagnosis should now be expired (thus considered invalid)
        assert current_diagnosis.expires_at == new_diagnosis.created_at
        assert not current_diagnosis.is_valid
        assert new_diagnosis.is_valid

    def test_update_diagnosis_extend_the_validity_only_when_we_have_the_same_author_and_the_same_criteria(self):
        first_diagnosis = EligibilityDiagnosisFactory()
        user_info = UserInfo(
            user=first_diagnosis.author,
            kind=first_diagnosis.author_kind,
            prescriber_organization=first_diagnosis.author_prescriber_organization,
            is_authorized_prescriber=first_diagnosis.author_prescriber_organization.is_authorized,
            siae=None,
        )

        # Same author, same criteria
        previous_expires_at = first_diagnosis.expires_at
        assert EligibilityDiagnosis.update_diagnosis(first_diagnosis, user_info, []) is first_diagnosis
        first_diagnosis.refresh_from_db()
        assert first_diagnosis.expires_at > previous_expires_at

        criteria = [
            AdministrativeCriteria.objects.get(level=AdministrativeCriteriaLevel.LEVEL_1, name="Bénéficiaire du RSA"),
        ]
        # Same author, different criteria
        second_diagnosis = EligibilityDiagnosis.update_diagnosis(first_diagnosis, user_info, criteria)
        first_diagnosis.refresh_from_db()

        assert second_diagnosis is not first_diagnosis
        assert first_diagnosis.expires_at == second_diagnosis.created_at
        assert second_diagnosis.expires_at > first_diagnosis.expires_at

        # Different author, same criteria
        other_prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
        other_user_info = UserInfo(
            user=other_prescriber_organization.members.first(),
            kind=AuthorKind.PRESCRIBER,
            prescriber_organization=other_prescriber_organization,
            is_authorized_prescriber=other_prescriber_organization.is_authorized,
            siae=None,
        )
        third_diagnosis = EligibilityDiagnosis.update_diagnosis(second_diagnosis, other_user_info, criteria)
        second_diagnosis.refresh_from_db()

        assert second_diagnosis is not third_diagnosis
        assert second_diagnosis.expires_at == third_diagnosis.created_at
        assert third_diagnosis.expires_at > second_diagnosis.expires_at

    def test_is_valid(self):
        # Valid diagnosis.
        diagnosis = EligibilityDiagnosisFactory()
        assert diagnosis.is_valid

        # Expired diagnosis.
        diagnosis = ExpiredEligibilityDiagnosisFactory()
        assert not diagnosis.is_valid

    def test_is_considered_valid(self):
        # Valid diagnosis.
        diagnosis = EligibilityDiagnosisFactory()
        assert diagnosis.is_considered_valid

        # Expired diagnosis.
        diagnosis = ExpiredEligibilityDiagnosisFactory()
        assert not diagnosis.is_considered_valid

        # Expired diagnosis but ongoing PASS IAE.
        diagnosis = ExpiredEligibilityDiagnosisFactory()
        ApprovalFactory(user=diagnosis.job_seeker)
        assert diagnosis.is_considered_valid


class AdministrativeCriteriaModelTest(TestCase):
    def test_levels_queryset(self):

        level1_criterion = AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_1).first()
        level2_criterion = AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_2).first()

        qs = AdministrativeCriteria.objects.level1()
        assert level1_criterion in qs
        assert level2_criterion not in qs

        qs = AdministrativeCriteria.objects.level2()
        assert level2_criterion in qs
        assert level1_criterion not in qs

    def test_for_job_application(self):
        siae = SiaeFactory(department="14", with_membership=True)

        job_seeker = JobSeekerFactory()
        user = siae.members.first()
        user_info = UserInfo(
            user=user,
            kind=AuthorKind.SIAE_STAFF,
            siae=siae,
            prescriber_organization=None,
            is_authorized_prescriber=False,
        )

        criteria1 = AdministrativeCriteria.objects.get(
            level=AdministrativeCriteriaLevel.LEVEL_1, name="Bénéficiaire du RSA"
        )
        eligibility_diagnosis = EligibilityDiagnosis.create_diagnosis(
            job_seeker, user_info, administrative_criteria=[criteria1]
        )

        job_application1 = JobApplicationFactory(
            with_approval=True,
            to_siae=siae,
            sender_siae=siae,
            eligibility_diagnosis=eligibility_diagnosis,
            hiring_start_at=timezone.now() - relativedelta(months=2),
        )

        job_application2 = JobApplicationFactory(
            with_approval=True,
            to_siae=siae,
            sender_siae=siae,
            hiring_start_at=timezone.now() - relativedelta(months=2),
        )

        assert isinstance(
            AdministrativeCriteria.objects.for_job_application(job_application1), AdministrativeCriteriaQuerySet
        )

        assert 1 == AdministrativeCriteria.objects.for_job_application(job_application1).count()
        assert criteria1 == AdministrativeCriteria.objects.for_job_application(job_application1).first()
        assert 0 == AdministrativeCriteria.objects.for_job_application(job_application2).count()

    def test_key_property(self):
        criterion_level_1 = AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_1).first()
        assert criterion_level_1.key == f"level_{criterion_level_1.level}_{criterion_level_1.pk}"

        criterion_level_2 = AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_2).first()
        assert criterion_level_2.key == f"level_{criterion_level_2.level}_{criterion_level_2.pk}"
