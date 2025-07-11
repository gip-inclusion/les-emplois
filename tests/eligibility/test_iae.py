import datetime
from functools import partial

import pytest
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertQuerySetEqual

from itou.eligibility.enums import (
    CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS,
    AdministrativeCriteriaKind,
    AdministrativeCriteriaLevel,
    AuthorKind,
)
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.eligibility.models.geiq import GEIQAdministrativeCriteria
from itou.eligibility.utils import _criteria_for_display
from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.job_applications.models import JobApplication
from itou.users.enums import IdentityCertificationAuthorities
from itou.users.models import IdentityCertification, JobSeekerProfile
from itou.utils.mocks.api_particulier import (
    RESPONSES,
    ResponseKind,
)
from itou.utils.types import InclusiveDateRange
from tests.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory
from tests.companies.factories import CompanyFactory
from tests.eligibility.factories import (
    GEIQEligibilityDiagnosisFactory,
    IAEEligibilityDiagnosisFactory,
)
from tests.prescribers.factories import PrescriberOrganizationFactory, PrescriberOrganizationWithMembershipFactory
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
        last_for_job_seeker = EligibilityDiagnosis.objects.last_for_job_seeker(job_seeker=self.job_seeker)
        assert last_considered_valid is None
        assert last_expired is None
        assert not has_considered_valid
        assert last_for_job_seeker is None

    def test_itou_diagnosis(self):
        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(job_seeker=diagnosis.job_seeker)
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=diagnosis.job_seeker)
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=diagnosis.job_seeker)
        last_for_job_seeker = EligibilityDiagnosis.objects.last_for_job_seeker(job_seeker=diagnosis.job_seeker)
        assert last_considered_valid == diagnosis
        assert last_expired is None
        assert has_considered_valid
        assert last_for_job_seeker == diagnosis

    def test_pole_emploi_diagnosis(self):
        PoleEmploiApprovalFactory(
            pole_emploi_id=self.job_seeker.jobseeker_profile.pole_emploi_id,
            birthdate=self.job_seeker.jobseeker_profile.birthdate,
        )
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(job_seeker=self.job_seeker)
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=self.job_seeker)
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=self.job_seeker)
        last_for_job_seeker = EligibilityDiagnosis.objects.last_for_job_seeker(job_seeker=self.job_seeker)
        assert not has_considered_valid  # Valid PoleEmploiApproval are now ignored
        assert last_considered_valid is None
        assert last_expired is None
        assert last_for_job_seeker is None

    def test_expired_pole_emploi_diagnosis(self):
        end_at = timezone.localdate() - relativedelta(years=2)
        start_at = end_at - relativedelta(years=2)
        PoleEmploiApprovalFactory(
            pole_emploi_id=self.job_seeker.jobseeker_profile.pole_emploi_id,
            birthdate=self.job_seeker.jobseeker_profile.birthdate,
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
        last_for_job_seeker = EligibilityDiagnosis.objects.last_for_job_seeker(job_seeker=expired_diagnosis.job_seeker)
        assert not has_considered_valid
        assert last_considered_valid is None
        assert last_expired is not None
        assert last_for_job_seeker == expired_diagnosis

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
        last_for_job_seeker = EligibilityDiagnosis.objects.last_for_job_seeker(job_seeker=expired_diagnosis.job_seeker)
        assert has_considered_valid
        assert last_considered_valid == expired_diagnosis
        assert last_expired is None
        assert last_for_job_seeker == expired_diagnosis

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
        # From job seeker perspective.
        last_for_job_seeker = EligibilityDiagnosis.objects.last_for_job_seeker(job_seeker=diagnosis.job_seeker)
        assert last_for_job_seeker is None
        # With an ongoing approval.
        approval = ApprovalFactory(user=self.job_seeker, eligibility_diagnosis=diagnosis, with_jobapplication=True)
        last_for_job_seeker = EligibilityDiagnosis.objects.last_for_job_seeker(job_seeker=diagnosis.job_seeker)
        assert last_for_job_seeker == diagnosis
        # A diagnosis and a PASS but they are not related.
        approval.delete()
        JobApplication.objects.all().delete()
        approval = ApprovalFactory(user=self.job_seeker)
        last_for_job_seeker = EligibilityDiagnosis.objects.last_for_job_seeker(job_seeker=diagnosis.job_seeker)
        assert last_for_job_seeker != diagnosis  # (the returned diagnosis is the one that lead to a PASS).

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
        # From job seeker perspective.
        last_for_job_seeker = EligibilityDiagnosis.objects.last_for_job_seeker(
            job_seeker=prescriber_diagnosis.job_seeker
        )
        assert last_for_job_seeker == prescriber_diagnosis

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
        # From job seeker perspective.
        last_for_job_seeker = EligibilityDiagnosis.objects.last_for_job_seeker(job_seeker=self.job_seeker)
        assert last_for_job_seeker == prescriber_diagnosis

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
        valid_diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=self.job_seeker)
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=self.job_seeker)
        last_for_job_seeker = EligibilityDiagnosis.objects.last_for_job_seeker(job_seeker=self.job_seeker)
        # When has a valid diagnosis, `last_expired` return None
        assert last_considered_valid is not None
        assert last_expired is None
        assert last_for_job_seeker == valid_diagnosis

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
        last_for_job_seeker = EligibilityDiagnosis.objects.last_for_job_seeker(job_seeker=self.job_seeker)
        assert last_expired == expired_diagnosis_old
        assert last_for_job_seeker == expired_diagnosis_old
        expired_diagnosis_last = IAEEligibilityDiagnosisFactory(
            from_prescriber=True, job_seeker=self.job_seeker, created_at=date_6m
        )
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=self.job_seeker)
        last_for_job_seeker = EligibilityDiagnosis.objects.last_for_job_seeker(job_seeker=self.job_seeker)
        assert last_expired == expired_diagnosis_last
        assert last_for_job_seeker == expired_diagnosis_last


class TestEligibilityDiagnosisModel:
    @freeze_time("2024-12-03")
    def test_create_diagnosis_employer(self):
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
        assert diagnosis.expires_at == datetime.date(2025, 3, 5)

        # Check GPS group
        # ----------------------------------------------------------------------
        group = FollowUpGroup.objects.get()
        assert group.beneficiary == job_seeker
        membership = FollowUpGroupMembership.objects.get(follow_up_group=group)
        assert membership.member == user
        assert membership.creator == user

    @freeze_time("2024-12-03")
    def test_create_diagnosis_prescriber(self):
        job_seeker = JobSeekerFactory()
        organization = PrescriberOrganizationWithMembershipFactory()
        prescriber = organization.members.first()

        diagnosis = EligibilityDiagnosis.create_diagnosis(
            job_seeker,
            author=prescriber,
            author_organization=organization,
        )

        assert diagnosis.job_seeker == job_seeker
        assert diagnosis.author == prescriber
        assert diagnosis.author_kind == AuthorKind.PRESCRIBER
        assert diagnosis.author_siae is None
        assert diagnosis.author_prescriber_organization == organization
        assert diagnosis.administrative_criteria.count() == 0
        assert diagnosis.expires_at == datetime.date(2025, 6, 3)

        # Check GPS group
        # ----------------------------------------------------------------------
        group = FollowUpGroup.objects.get()
        assert group.beneficiary == job_seeker
        membership = FollowUpGroupMembership.objects.get(follow_up_group=group)
        assert membership.member == prescriber
        assert membership.creator == prescriber

    def test_create_diagnosis_with_administrative_criteria(self):
        job_seeker = JobSeekerFactory()
        prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
        user = prescriber_organization.members.first()

        level1 = AdministrativeCriteriaLevel.LEVEL_1
        level2 = AdministrativeCriteriaLevel.LEVEL_2
        criteria1 = AdministrativeCriteria.objects.get(level=level1, kind=AdministrativeCriteriaKind.RSA)
        criteria2 = AdministrativeCriteria.objects.get(level=level2, kind=AdministrativeCriteriaKind.CAP_BEP)
        criteria3 = AdministrativeCriteria.objects.get(level=level2, kind=AdministrativeCriteriaKind.SENIOR)

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

    @pytest.mark.parametrize("organization_factory", [CompanyFactory, PrescriberOrganizationFactory])
    def test_create_diagnosis_certify_certifiable_criteria(self, mocker, organization_factory):
        criterion = AdministrativeCriteria.objects.certifiable().order_by("?").first()
        mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[criterion.kind][ResponseKind.CERTIFIED],
        )
        organization = organization_factory(with_membership=True)

        diagnosis = EligibilityDiagnosis.create_diagnosis(
            JobSeekerFactory(certifiable=True),
            author=organization.members.first(),
            author_organization=organization,
            administrative_criteria=[criterion],
        )
        [criterion] = _criteria_for_display(
            [diagnosis.selected_administrative_criteria.get()], hiring_start_at=timezone.localdate()
        )
        assert criterion.is_considered_certified is True

    @freeze_time("2024-12-03")
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
        assert new_diagnosis.expires_at == datetime.date(2025, 3, 5)

        # And the old diagnosis should now be expired (thus considered invalid)
        assert current_diagnosis.expires_at == timezone.localdate(new_diagnosis.created_at)
        assert not current_diagnosis.is_valid
        assert new_diagnosis.is_valid

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

        # Expired diagnosis but ongoing PASS IAE, not associated to the diagnosis.
        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, expired=True)
        approval = ApprovalFactory(user=diagnosis.job_seeker)
        assert diagnosis.is_considered_valid is False

        # Expired diagnosis but ongoing PASS IAE, associated to the diagnosis.
        approval.eligibility_diagnosis = diagnosis
        approval.save()
        assert diagnosis.is_considered_valid


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

    def test_key_property(self):
        criterion_level_1 = AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_1).first()
        assert criterion_level_1.key == f"level_{criterion_level_1.level}_{criterion_level_1.pk}"

        criterion_level_2 = AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_2).first()
        assert criterion_level_2.key == f"level_{criterion_level_2.level}_{criterion_level_2.pk}"


@pytest.mark.parametrize(
    "AdministrativeCriteriaClass",
    [
        pytest.param(AdministrativeCriteria, id="test_certifiable_iae"),
        pytest.param(GEIQAdministrativeCriteria, id="test_certifiable_geiq"),
    ],
)
def test_certifiable(AdministrativeCriteriaClass):
    for criterion in AdministrativeCriteriaClass.objects.all():
        assert AdministrativeCriteriaKind(criterion.kind)

    certifiable_criteria = AdministrativeCriteriaClass.objects.filter(
        kind__in=CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS
    )
    not_certifiable_criteria = AdministrativeCriteriaClass.objects.exclude(
        kind__in=CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS
    ).all()

    for criterion in certifiable_criteria:
        assert criterion in AdministrativeCriteriaClass.objects.certifiable()
        assert criterion.is_certifiable

    for criterion in not_certifiable_criteria:
        assert criterion in not_certifiable_criteria
        assert not criterion.is_certifiable


@pytest.mark.parametrize(
    "EligibilityDiagnosisFactory", [IAEEligibilityDiagnosisFactory, GEIQEligibilityDiagnosisFactory]
)
@pytest.mark.parametrize("criteria_kind", CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS)
@freeze_time("2024-09-12")
def test_eligibility_diagnosis_certify_criteria(mocker, EligibilityDiagnosisFactory, criteria_kind):
    mocker.patch(
        "itou.utils.apis.api_particulier._request",
        return_value=RESPONSES[criteria_kind][ResponseKind.CERTIFIED],
    )
    job_seeker = JobSeekerFactory(with_address=True, born_in_france=True)
    eligibility_diagnosis = EligibilityDiagnosisFactory(
        job_seeker=job_seeker, certifiable=True, criteria_kinds=[criteria_kind]
    )
    eligibility_diagnosis.certify_criteria()

    SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
    criterion = SelectedAdministrativeCriteria.objects.get(
        administrative_criteria__kind=criteria_kind,
        eligibility_diagnosis=eligibility_diagnosis,
    )
    assert criterion.certified is True
    assert criterion.certified_at == timezone.now()
    assert criterion.data_returned_by_api == RESPONSES[criteria_kind][ResponseKind.CERTIFIED]
    assert criterion.certification_period == InclusiveDateRange(datetime.date(2024, 8, 1), datetime.date(2024, 12, 13))
    certification = IdentityCertification.objects.get(jobseeker_profile=job_seeker.jobseeker_profile)
    assert certification.certifier == IdentityCertificationAuthorities.API_PARTICULIER
    with freeze_time("2025-10-15"):
        eligibility_diagnosis.certify_criteria()
    updated_certification = IdentityCertification.objects.get(jobseeker_profile=job_seeker.jobseeker_profile)
    assert updated_certification.certifier == IdentityCertificationAuthorities.API_PARTICULIER
    assert updated_certification.certified_at > certification.certified_at


@pytest.mark.parametrize(
    "EligibilityDiagnosisFactory",
    [
        pytest.param(
            partial(IAEEligibilityDiagnosisFactory, from_employer=True),
            id="test_selected_administrative_criteria_certify_iae",
        ),
        pytest.param(
            partial(GEIQEligibilityDiagnosisFactory, from_employer=True),
            id="test_selected_administrative_criteria_certify_geiq",
        ),
    ],
)
def test_eligibility_diagnosis_certify_criteria_missing_info(respx_mock, EligibilityDiagnosisFactory):
    RSA_ENDPOINT = f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active"
    respx_mock.get(RSA_ENDPOINT).mock(side_effect=Exception)
    job_seeker = JobSeekerFactory()  # Missing data.
    eligibility_diagnosis = EligibilityDiagnosisFactory(
        job_seeker=job_seeker,
        certifiable=True,
        criteria_kinds=[AdministrativeCriteriaKind.RSA],
    )
    eligibility_diagnosis.certify_criteria()
    assert len(respx_mock.calls) == 0
    jobseeker_profile = JobSeekerProfile.objects.get(pk=job_seeker.jobseeker_profile)
    assertQuerySetEqual(jobseeker_profile.identity_certifications.all(), [])


@freeze_time("2024-09-12T00:00:00Z")
@pytest.mark.parametrize(
    "EligibilityDiagnosisFactory,identity_certifiers,expected,response_status,response",
    [
        pytest.param(
            partial(IAEEligibilityDiagnosisFactory, from_employer=True),
            [IdentityCertificationAuthorities.API_PARTICULIER],
            {
                "certification_period": InclusiveDateRange(datetime.date(2024, 8, 1), datetime.date(2024, 12, 13)),
                "certified": True,
                "certified_at": datetime.datetime(2024, 9, 12, tzinfo=datetime.UTC),
                "data_returned_by_api": RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.CERTIFIED],
            },
            200,
            RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.CERTIFIED],
            id="iae-certified",
        ),
        pytest.param(
            partial(GEIQEligibilityDiagnosisFactory, from_employer=True),
            [IdentityCertificationAuthorities.API_PARTICULIER],
            {
                "certification_period": InclusiveDateRange(datetime.date(2024, 8, 1), datetime.date(2024, 12, 13)),
                "certified": True,
                "certified_at": datetime.datetime(2024, 9, 12, tzinfo=datetime.UTC),
                "data_returned_by_api": RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.CERTIFIED],
            },
            200,
            RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.CERTIFIED],
            id="geiq-certified",
        ),
        pytest.param(
            partial(IAEEligibilityDiagnosisFactory, from_employer=True),
            [IdentityCertificationAuthorities.API_PARTICULIER],
            {
                "certification_period": None,
                "certified": False,
                "certified_at": datetime.datetime(2024, 9, 12, tzinfo=datetime.UTC),
                "data_returned_by_api": RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.NOT_CERTIFIED],
            },
            200,
            RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.NOT_CERTIFIED],
            id="iae-not-certified",
        ),
        pytest.param(
            partial(GEIQEligibilityDiagnosisFactory, from_employer=True),
            [IdentityCertificationAuthorities.API_PARTICULIER],
            {
                "certification_period": None,
                "certified": False,
                "certified_at": datetime.datetime(2024, 9, 12, tzinfo=datetime.UTC),
                "data_returned_by_api": RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.NOT_CERTIFIED],
            },
            200,
            RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.NOT_CERTIFIED],
            id="geiq-not-certified",
        ),
        pytest.param(
            partial(IAEEligibilityDiagnosisFactory, from_employer=True),
            [],
            {
                "certification_period": None,
                "certified": None,
                "certified_at": datetime.datetime(2024, 9, 12, tzinfo=datetime.UTC),
                "data_returned_by_api": RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.NOT_FOUND],
            },
            404,
            RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.NOT_FOUND],
            id="iae-not-found",
        ),
        pytest.param(
            partial(GEIQEligibilityDiagnosisFactory, from_employer=True),
            [],
            {
                "certification_period": None,
                "certified": None,
                "certified_at": datetime.datetime(2024, 9, 12, tzinfo=datetime.UTC),
                "data_returned_by_api": RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.NOT_FOUND],
            },
            404,
            RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.NOT_FOUND],
            id="geiq-not-found",
        ),
    ],
)
def test_selected_administrative_criteria_certified(
    expected, identity_certifiers, response, response_status, respx_mock, EligibilityDiagnosisFactory
):
    eligibility_diagnosis = EligibilityDiagnosisFactory(
        certifiable=True,
        criteria_kinds=[AdministrativeCriteriaKind.RSA],
    )
    respx_mock.get(f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active").respond(
        response_status, json=response
    )

    eligibility_diagnosis.certify_criteria()

    SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
    criterion = SelectedAdministrativeCriteria.objects.filter(
        administrative_criteria__kind=AdministrativeCriteriaKind.RSA,
        eligibility_diagnosis=eligibility_diagnosis,
    ).get()
    for attrname, value in expected.items():
        assert getattr(criterion, attrname) == value
    assert len(respx_mock.calls) == 1
    jobseeker_profile = JobSeekerProfile.objects.get(pk=eligibility_diagnosis.job_seeker.jobseeker_profile)
    assertQuerySetEqual(
        jobseeker_profile.identity_certifications.all(),
        identity_certifiers,
        transform=lambda certification: certification.certifier,
    )


def test_is_from_employer():
    diagnosis = GEIQEligibilityDiagnosisFactory(from_employer=True)
    assert diagnosis.is_from_employer

    diagnosis = GEIQEligibilityDiagnosisFactory(from_prescriber=True)
    assert not diagnosis.is_from_employer

    diagnosis = IAEEligibilityDiagnosisFactory(from_employer=True)
    assert diagnosis.is_from_employer

    diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True)
    assert not diagnosis.is_from_employer
