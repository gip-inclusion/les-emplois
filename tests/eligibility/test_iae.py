import datetime

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from itou.eligibility.enums import AdministrativeCriteriaLevel, AuthorKind
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.eligibility.models.common import AdministrativeCriteriaQuerySet
from tests.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory
from tests.companies.factories import CompanyFactory
from tests.eligibility.factories import (
    IAEEligibilityDiagnosisFactory,
)
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import JobSeekerFactory


class TestEligibilityDiagnosisQuerySet:
    """
    Test EligibilityDiagnosisQuerySet.
    """

    def test_valid(self):
        expected_num = 5
        IAEEligibilityDiagnosisFactory.create_batch(expected_num, from_prescriber=True)
        IAEEligibilityDiagnosisFactory.create_batch(expected_num, from_prescriber=True, expired=True)
        assert expected_num * 2 == EligibilityDiagnosis.objects.all().count()
        assert expected_num == EligibilityDiagnosis.objects.valid().count()

    def test_expired(self):
        expected_num = 3
        IAEEligibilityDiagnosisFactory.create_batch(expected_num, from_prescriber=True)
        IAEEligibilityDiagnosisFactory.create_batch(expected_num, from_prescriber=True, expired=True)
        assert expected_num * 2 == EligibilityDiagnosis.objects.all().count()
        assert expected_num == EligibilityDiagnosis.objects.expired().count()


class TestEligibilityDiagnosisManager:
    def setup_method(self):
        self.job_seeker = JobSeekerFactory(with_pole_emploi_id=True)

    def test_no_diagnosis(self):
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(job_seeker=self.job_seeker)
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=self.job_seeker)
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=self.job_seeker)
        assert last_considered_valid is None
        assert last_expired is None
        assert not has_considered_valid

    def test_itou_diagnosis(self):
        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(job_seeker=diagnosis.job_seeker)
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=diagnosis.job_seeker)
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=diagnosis.job_seeker)
        assert last_considered_valid == diagnosis
        assert last_expired is None
        assert has_considered_valid

    def test_pole_emploi_diagnosis(self):
        PoleEmploiApprovalFactory(
            pole_emploi_id=self.job_seeker.jobseeker_profile.pole_emploi_id, birthdate=self.job_seeker.birthdate
        )
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(job_seeker=self.job_seeker)
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=self.job_seeker)
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=self.job_seeker)
        assert has_considered_valid
        assert last_considered_valid is None
        assert last_expired is None

    def test_expired_pole_emploi_diagnosis(self):
        end_at = datetime.date.today() - relativedelta(years=2)
        start_at = end_at - relativedelta(years=2)
        PoleEmploiApprovalFactory(
            pole_emploi_id=self.job_seeker.jobseeker_profile.pole_emploi_id,
            birthdate=self.job_seeker.birthdate,
            start_at=start_at,
            end_at=end_at,
        )
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(job_seeker=self.job_seeker)
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=self.job_seeker)
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=self.job_seeker)
        assert not has_considered_valid
        assert last_considered_valid is None
        assert last_expired is None

    def test_expired_itou_diagnosis(self):
        expired_diagnosis = IAEEligibilityDiagnosisFactory(
            from_prescriber=True, job_seeker=self.job_seeker, expired=True
        )
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

    def test_expired_itou_diagnosis_with_ongoing_approval(self):
        expired_diagnosis = IAEEligibilityDiagnosisFactory(
            from_prescriber=True, job_seeker=self.job_seeker, expired=True
        )
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

    def test_itou_diagnosis_by_siae(self):
        company_1 = CompanyFactory(with_membership=True)
        company_2 = CompanyFactory(with_membership=True)
        diagnosis = IAEEligibilityDiagnosisFactory(
            from_employer=True, author_siae=company_1, job_seeker=self.job_seeker
        )
        # From `company_1` perspective.
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(
            job_seeker=diagnosis.job_seeker, for_siae=company_1
        )
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(
            job_seeker=diagnosis.job_seeker, for_siae=company_1
        )
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=diagnosis.job_seeker, for_siae=company_1)
        assert has_considered_valid
        assert last_considered_valid == diagnosis
        assert last_expired is None
        # From `company_2` perspective.
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(
            job_seeker=diagnosis.job_seeker, for_siae=company_2
        )
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(
            job_seeker=diagnosis.job_seeker, for_siae=company_2
        )
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=diagnosis.job_seeker, for_siae=company_2)
        assert not has_considered_valid
        assert last_considered_valid is None
        assert last_expired is None

    def test_itou_diagnosis_by_prescriber(self):
        company = CompanyFactory(with_membership=True)
        prescriber_diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)
        # From siae perspective.
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(
            job_seeker=prescriber_diagnosis.job_seeker, for_siae=company
        )
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(
            job_seeker=prescriber_diagnosis.job_seeker, for_siae=company
        )
        last_expired = EligibilityDiagnosis.objects.last_expired(
            job_seeker=prescriber_diagnosis.job_seeker, for_siae=company
        )
        assert has_considered_valid
        assert last_considered_valid == prescriber_diagnosis
        assert last_expired is None

    def test_itou_diagnosis_both_siae_and_prescriber(self):
        company = CompanyFactory(with_membership=True)
        prescriber_diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)
        # From `siae` perspective.
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(
            job_seeker=self.job_seeker, for_siae=company
        )
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(
            job_seeker=self.job_seeker, for_siae=company
        )
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=self.job_seeker, for_siae=company)
        assert has_considered_valid
        # A diagnosis made by a prescriber takes precedence.
        assert last_considered_valid == prescriber_diagnosis
        assert last_expired is None

    def test_expired_itou_diagnosis_by_another_siae(self):
        company_1 = CompanyFactory(with_membership=True)
        company_2 = CompanyFactory(with_membership=True)
        expired_diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            from_employer=True,
            author_siae=company_1,
            expired=True,
        )
        # From `siae` perspective.
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=self.job_seeker, for_siae=company_1)
        assert last_expired == expired_diagnosis
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=self.job_seeker, for_siae=company_2)
        assert last_expired is None

    def test_itou_diagnosis_one_valid_other_expired(self):
        IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker, expired=True)
        IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=self.job_seeker)
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=self.job_seeker)
        # When has a valid diagnosis, `last_expired` return None
        assert last_considered_valid is not None
        assert last_expired is None

    def test_itou_diagnosis_one_valid_other_expired_same_siae(self):
        company = CompanyFactory(with_membership=True)
        IAEEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_siae=company,
            from_employer=True,
            expired=True,
        )
        new_diag = IAEEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_siae=company,
            from_employer=True,
        )
        # An approval causes the system to ignore expires_at.
        ApprovalFactory(user=self.job_seeker, eligibility_diagnosis=new_diag)
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(
            job_seeker=self.job_seeker, for_siae=company
        )
        assert last_considered_valid == new_diag

    def test_itou_diagnosis_expired_uses_the_most_recent(self):
        date_6m = (
            timezone.now() - relativedelta(months=EligibilityDiagnosis.EXPIRATION_DELAY_MONTHS) - relativedelta(day=1)
        )
        date_12m = date_6m - relativedelta(months=6)
        expired_diagnosis_old = IAEEligibilityDiagnosisFactory(
            from_prescriber=True, job_seeker=self.job_seeker, created_at=date_12m
        )
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=self.job_seeker)
        assert last_expired == expired_diagnosis_old
        expired_diagnosis_last = IAEEligibilityDiagnosisFactory(
            from_prescriber=True, job_seeker=self.job_seeker, created_at=date_6m
        )
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=self.job_seeker)
        assert last_expired == expired_diagnosis_last


class TestEligibilityDiagnosisModel:
    def test_create_diagnosis(self):
        job_seeker = JobSeekerFactory()
        company = CompanyFactory(with_membership=True)
        user = company.members.first()

        diagnosis = EligibilityDiagnosis.create_diagnosis(job_seeker, author=user, author_organization=company)

        assert diagnosis.job_seeker == job_seeker
        assert diagnosis.author == user
        assert diagnosis.author_kind == AuthorKind.EMPLOYER
        assert diagnosis.author_siae == company
        assert diagnosis.author_prescriber_organization is None
        assert diagnosis.administrative_criteria.count() == 0

    def test_create_diagnosis_with_administrative_criteria(self):
        job_seeker = JobSeekerFactory()
        prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
        user = prescriber_organization.members.first()

        level1 = AdministrativeCriteriaLevel.LEVEL_1
        level2 = AdministrativeCriteriaLevel.LEVEL_2
        criteria1 = AdministrativeCriteria.objects.get(level=level1, name="Bénéficiaire du RSA")
        criteria2 = AdministrativeCriteria.objects.get(level=level2, name="Niveau d'étude 3 (CAP, BEP) ou infra")
        criteria3 = AdministrativeCriteria.objects.get(level=level2, name="Senior (+50 ans)")

        diagnosis = EligibilityDiagnosis.create_diagnosis(
            job_seeker,
            author=user,
            author_organization=prescriber_organization,
            administrative_criteria=[criteria1, criteria2, criteria3],
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
        company = CompanyFactory(with_membership=True)

        current_diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True)
        new_diagnosis = EligibilityDiagnosis.update_diagnosis(
            current_diagnosis, author=company.members.first(), author_organization=company, administrative_criteria=[]
        )
        current_diagnosis.refresh_from_db()

        # Some information should be copied...
        assert new_diagnosis.job_seeker == current_diagnosis.job_seeker
        # ... or updated.
        assert new_diagnosis.author == company.members.first()
        assert new_diagnosis.author_kind == AuthorKind.EMPLOYER
        assert new_diagnosis.author_siae == company
        assert new_diagnosis.author_prescriber_organization is None
        assert new_diagnosis.administrative_criteria.count() == 0

        # And the old diagnosis should now be expired (thus considered invalid)
        assert current_diagnosis.expires_at == new_diagnosis.created_at
        assert not current_diagnosis.is_valid
        assert new_diagnosis.is_valid

    def test_update_diagnosis_extend_the_validity_only_when_we_have_the_same_author_and_the_same_criteria(self):
        first_diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True)

        # Same author, same criteria
        previous_expires_at = first_diagnosis.expires_at
        assert (
            EligibilityDiagnosis.update_diagnosis(
                first_diagnosis,
                author=first_diagnosis.author,
                author_organization=first_diagnosis.author_prescriber_organization,
                administrative_criteria=[],
            )
            is first_diagnosis
        )
        first_diagnosis.refresh_from_db()
        assert first_diagnosis.expires_at > previous_expires_at

        criteria = [
            AdministrativeCriteria.objects.get(level=AdministrativeCriteriaLevel.LEVEL_1, name="Bénéficiaire du RSA"),
        ]
        # Same author, different criteria
        second_diagnosis = EligibilityDiagnosis.update_diagnosis(
            first_diagnosis,
            author=first_diagnosis.author,
            author_organization=first_diagnosis.author_prescriber_organization,
            administrative_criteria=criteria,
        )
        first_diagnosis.refresh_from_db()

        assert second_diagnosis is not first_diagnosis
        assert first_diagnosis.expires_at == second_diagnosis.created_at
        assert second_diagnosis.expires_at > first_diagnosis.expires_at

        # Different author, same criteria
        other_prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
        third_diagnosis = EligibilityDiagnosis.update_diagnosis(
            second_diagnosis,
            author=other_prescriber_organization.members.first(),
            author_organization=other_prescriber_organization,
            administrative_criteria=criteria,
        )
        second_diagnosis.refresh_from_db()

        assert second_diagnosis is not third_diagnosis
        assert second_diagnosis.expires_at == third_diagnosis.created_at
        assert third_diagnosis.expires_at > second_diagnosis.expires_at

    def test_is_valid(self):
        # Valid diagnosis.
        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True)
        assert diagnosis.is_valid

        # Expired diagnosis.
        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, expired=True)
        assert not diagnosis.is_valid

    def test_is_considered_valid(self):
        # Valid diagnosis.
        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True)
        assert diagnosis.is_considered_valid

        # Expired diagnosis.
        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, expired=True)
        assert not diagnosis.is_considered_valid

        # Expired diagnosis but ongoing PASS IAE.
        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, expired=True)
        ApprovalFactory(user=diagnosis.job_seeker)
        assert diagnosis.is_considered_valid

    def test_criteria_certification_required(self):
        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, with_certifiable_criteria=True)
        assert diagnosis.criteria_certification_required

        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, with_not_certifiable_criteria=True)
        assert not diagnosis.criteria_certification_required


class TestAdministrativeCriteriaModel:
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
        company = CompanyFactory(department="14", with_membership=True)

        job_seeker = JobSeekerFactory()
        user = company.members.first()

        criteria1 = AdministrativeCriteria.objects.get(
            level=AdministrativeCriteriaLevel.LEVEL_1, name="Bénéficiaire du RSA"
        )
        eligibility_diagnosis = EligibilityDiagnosis.create_diagnosis(
            job_seeker, author=user, author_organization=company, administrative_criteria=[criteria1]
        )

        job_application1 = JobApplicationFactory(
            with_approval=True,
            to_company=company,
            sender_company=company,
            eligibility_diagnosis=eligibility_diagnosis,
            hiring_start_at=timezone.now() - relativedelta(months=2),
        )

        job_application2 = JobApplicationFactory(
            with_approval=True,
            to_company=company,
            sender_company=company,
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


class AdministrativeCriteriaQuerysetTest(TestCase):
    # TODO(cms): move some AdministrativeCriteriaModelTest here.
    def test_certifiable(self):
        expected = AdministrativeCriteria.objects.filter(certifiable=True).first()
        not_expected = AdministrativeCriteria.objects.exclude(certifiable=True).first()
        assert expected in AdministrativeCriteria.objects.certifiable()
        assert not_expected not in AdministrativeCriteria.objects.certifiable()

        expected = AdministrativeCriteria.objects.exclude(certifiable=True).first()
        not_expected = AdministrativeCriteria.objects.filter(certifiable=True).first()
        assert expected in AdministrativeCriteria.objects.not_certifiable()
        assert not_expected not in AdministrativeCriteria.objects.not_certifiable()
