import datetime
from functools import partial

import pytest
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.utils import timezone
from freezegun import freeze_time

from itou.eligibility.enums import (
    CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS,
    AdministrativeCriteriaKind,
    AdministrativeCriteriaLevel,
    AuthorKind,
)
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.eligibility.models.common import (
    AbstractSelectedAdministrativeCriteria,
    AdministrativeCriteriaQuerySet,
)
from itou.eligibility.models.geiq import GEIQAdministrativeCriteria
from itou.utils.mocks.api_particulier import (
    rsa_certified_mocker,
    rsa_not_certified_mocker,
    rsa_not_found_mocker,
)
from itou.utils.types import InclusiveDateRange
from tests.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory
from tests.companies.factories import CompanyFactory
from tests.eligibility.factories import (
    GEIQEligibilityDiagnosisFactory,
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
            pole_emploi_id=self.job_seeker.jobseeker_profile.pole_emploi_id,
            birthdate=self.job_seeker.jobseeker_profile.birthdate,
        )
        has_considered_valid = EligibilityDiagnosis.objects.has_considered_valid(job_seeker=self.job_seeker)
        last_considered_valid = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=self.job_seeker)
        last_expired = EligibilityDiagnosis.objects.last_expired(job_seeker=self.job_seeker)
        assert not has_considered_valid  # Valid PoleEmploiApproval are now ignored
        assert last_considered_valid is None
        assert last_expired is None

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

        # Expired diagnosis but ongoing PASS IAE.
        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, expired=True)
        ApprovalFactory(user=diagnosis.job_seeker)
        assert diagnosis.is_considered_valid

    @pytest.mark.parametrize(
        "factory_params,expected",
        [
            pytest.param(
                {"from_prescriber": True, "with_certifiable_criteria": True}, False, id="prescriber_certified_criteria"
            ),
            pytest.param(
                {"from_prescriber": True, "with_not_certifiable_criteria": True},
                False,
                id="prescriber_no_certified_criteria",
            ),
            pytest.param(
                {"from_employer": True, "with_not_certifiable_criteria": True},
                False,
                id="employer_no_certified_criteria",
            ),
            pytest.param(
                {"from_employer": True, "with_certifiable_criteria": True}, True, id="employer_certified_criteria"
            ),
        ],
    )
    def test_criteria_can_be_certified(self, factory_params, expected):
        diagnosis = IAEEligibilityDiagnosisFactory(**factory_params)
        assert diagnosis.criteria_can_be_certified() == expected


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

    certifiable_criterion = AdministrativeCriteriaClass.objects.get(kind=AdministrativeCriteriaKind.RSA)
    not_certifiable_criteria = AdministrativeCriteriaClass.objects.exclude(kind=AdministrativeCriteriaKind.RSA).all()

    assert certifiable_criterion in AdministrativeCriteriaClass.objects.certifiable()
    assert certifiable_criterion.is_certifiable

    for criterion in not_certifiable_criteria:
        assert criterion in not_certifiable_criteria
        assert not criterion.is_certifiable


@pytest.mark.parametrize(
    "EligibilityDiagnosisFactory",
    [
        pytest.param(
            partial(IAEEligibilityDiagnosisFactory, from_employer=True),
            id="test_eligibility_diagnosis_certify_criteria_iae",
        ),
        pytest.param(
            partial(GEIQEligibilityDiagnosisFactory, from_geiq=True),
            id="test_eligibility_diagnosis_certify_criteria_geiq",
        ),
    ],
)
@freeze_time("2024-09-12")
def test_eligibility_diagnosis_certify_criteria(mocker, EligibilityDiagnosisFactory):
    mocker.patch(
        "itou.utils.apis.api_particulier._request",
        return_value=rsa_certified_mocker(),
    )
    job_seeker = JobSeekerFactory(with_address=True, born_in_france=True)
    eligibility_diagnosis = EligibilityDiagnosisFactory(with_certifiable_criteria=True, job_seeker=job_seeker)
    eligibility_diagnosis.certify_criteria()

    SelectedAdministrativeCriteria = eligibility_diagnosis.administrative_criteria.through
    criterion = SelectedAdministrativeCriteria.objects.get(
        administrative_criteria__kind__in=CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS,
        eligibility_diagnosis=eligibility_diagnosis,
    )
    assert criterion.certified is True
    assert criterion.certified_at == timezone.now()
    assert criterion.data_returned_by_api == rsa_certified_mocker()
    assert criterion.certification_period == InclusiveDateRange(datetime.date(2024, 8, 1), datetime.date(2024, 10, 31))


@pytest.mark.parametrize(
    "EligibilityDiagnosisFactory",
    [
        pytest.param(
            partial(IAEEligibilityDiagnosisFactory, from_employer=True),
            id="test_selected_administrative_criteria_certify_iae",
        ),
        pytest.param(
            partial(GEIQEligibilityDiagnosisFactory, from_geiq=True),
            id="test_selected_administrative_criteria_certify_geiq",
        ),
    ],
)
def test_eligibility_diagnosis_certify_criteria_missing_info(respx_mock, EligibilityDiagnosisFactory):
    RSA_ENDPOINT = f"{settings.API_PARTICULIER_BASE_URL}v2/revenu-solidarite-active"
    respx_mock.get(RSA_ENDPOINT).mock(side_effect=Exception)
    job_seeker = JobSeekerFactory()  # Missing data.
    eligibility_diagnosis = EligibilityDiagnosisFactory(with_certifiable_criteria=True, job_seeker=job_seeker)
    eligibility_diagnosis.certify_criteria()
    assert len(respx_mock.calls) == 0


@freeze_time("2024-09-12T00:00:00Z")
@pytest.mark.parametrize(
    "EligibilityDiagnosisFactory,expected,response_status,response",
    [
        pytest.param(
            partial(IAEEligibilityDiagnosisFactory, from_employer=True),
            {
                "certification_period": InclusiveDateRange(datetime.date(2024, 8, 1), datetime.date(2024, 10, 31)),
                "certified": True,
                "certified_at": datetime.datetime(2024, 9, 12, tzinfo=datetime.UTC),
                "data_returned_by_api": rsa_certified_mocker(),
            },
            200,
            rsa_certified_mocker(),
            id="iae-certified",
        ),
        pytest.param(
            partial(GEIQEligibilityDiagnosisFactory, from_geiq=True),
            {
                "certification_period": InclusiveDateRange(datetime.date(2024, 8, 1), datetime.date(2024, 10, 31)),
                "certified": True,
                "certified_at": datetime.datetime(2024, 9, 12, tzinfo=datetime.UTC),
                "data_returned_by_api": rsa_certified_mocker(),
            },
            200,
            rsa_certified_mocker(),
            id="geiq-certified",
        ),
        pytest.param(
            partial(IAEEligibilityDiagnosisFactory, from_employer=True),
            {
                "certification_period": None,
                "certified": False,
                "certified_at": datetime.datetime(2024, 9, 12, tzinfo=datetime.UTC),
                "data_returned_by_api": rsa_not_certified_mocker(),
            },
            200,
            rsa_not_certified_mocker(),
            id="iae-not-certified",
        ),
        pytest.param(
            partial(GEIQEligibilityDiagnosisFactory, from_geiq=True),
            {
                "certification_period": None,
                "certified": False,
                "certified_at": datetime.datetime(2024, 9, 12, tzinfo=datetime.UTC),
                "data_returned_by_api": rsa_not_certified_mocker(),
            },
            200,
            rsa_not_certified_mocker(),
            id="geiq-not-certified",
        ),
        pytest.param(
            partial(IAEEligibilityDiagnosisFactory, from_employer=True),
            {
                "certification_period": None,
                "certified": None,
                "certified_at": datetime.datetime(2024, 9, 12, tzinfo=datetime.UTC),
                "data_returned_by_api": rsa_not_found_mocker(),
            },
            404,
            rsa_not_found_mocker(),
            id="iae-not-found",
        ),
        pytest.param(
            partial(GEIQEligibilityDiagnosisFactory, from_geiq=True),
            {
                "certification_period": None,
                "certified": None,
                "certified_at": datetime.datetime(2024, 9, 12, tzinfo=datetime.UTC),
                "data_returned_by_api": rsa_not_found_mocker(),
            },
            404,
            rsa_not_found_mocker(),
            id="geiq-not-found",
        ),
    ],
)
def test_selected_administrative_criteria_certified(
    expected, response, response_status, respx_mock, EligibilityDiagnosisFactory
):
    job_seeker = JobSeekerFactory(with_address=True, born_in_france=True)
    eligibility_diagnosis = EligibilityDiagnosisFactory(with_certifiable_criteria=True, job_seeker=job_seeker)
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


def test_with_is_considered_certified():
    def assert_considered_valid_count(hiring_start_at, expected):
        assert (
            diagnosis.selected_administrative_criteria.with_is_considered_certified(hiring_start_at)
            .filter(is_considered_certified=True)
            .count()
            == expected
        )

    diagnosis = IAEEligibilityDiagnosisFactory(with_certifiable_criteria=True, from_employer=True)
    for selected_criterion in diagnosis.selected_administrative_criteria.all():
        selected_criterion.certified = True
        certification_period_start = timezone.now() - datetime.timedelta(days=10)
        certification_period_end = timezone.now() + datetime.timedelta(days=20)
        selected_criterion.certification_period = InclusiveDateRange(
            certification_period_start, certification_period_end
        )
        selected_criterion.save()
    assert (
        diagnosis.selected_administrative_criteria.with_is_considered_certified().count()
        == diagnosis.selected_administrative_criteria.count()
    )

    criterion_to_keep = diagnosis.selected_administrative_criteria.all()[:1]
    diagnosis.selected_administrative_criteria.exclude(pk__in=criterion_to_keep).delete()
    assert diagnosis.selected_administrative_criteria.count() == 1

    # no hiring_start_at: none is certified.
    assert_considered_valid_count(hiring_start_at=None, expected=0)

    # hiring_start_at within certification period.
    assert_considered_valid_count(hiring_start_at=timezone.now(), expected=1)

    # hiring_start_at before certification period beginning.
    hiring_start_at = certification_period_start - datetime.timedelta(days=1)
    assert_considered_valid_count(hiring_start_at=hiring_start_at, expected=0)

    # hiring_start_at on certification period beginning.
    assert_considered_valid_count(hiring_start_at=certification_period_start, expected=1)

    # hiring_start_at on certification period ending.
    assert_considered_valid_count(hiring_start_at=certification_period_end, expected=1)

    # hiring start_at after certification period ending.
    hiring_start_at = certification_period_end + datetime.timedelta(days=1)
    assert_considered_valid_count(hiring_start_at=hiring_start_at, expected=1)

    # hiring start_at after certification period ending + grace period almost finished.
    hiring_start_at = certification_period_end + datetime.timedelta(
        days=AbstractSelectedAdministrativeCriteria.CERTIFICATION_GRACE_PERIOD_DAYS
    )
    assert_considered_valid_count(hiring_start_at=hiring_start_at, expected=1)

    # hiring start_at after certification period ending + grace period.
    hiring_start_at = certification_period_end + datetime.timedelta(
        days=AbstractSelectedAdministrativeCriteria.CERTIFICATION_GRACE_PERIOD_DAYS + 1
    )
    assert_considered_valid_count(hiring_start_at=hiring_start_at, expected=0)


def test_is_from_employer():
    diagnosis = GEIQEligibilityDiagnosisFactory(from_geiq=True)
    assert diagnosis.is_from_employer

    diagnosis = GEIQEligibilityDiagnosisFactory(from_prescriber=True)
    assert not diagnosis.is_from_employer

    diagnosis = IAEEligibilityDiagnosisFactory(from_employer=True)
    assert diagnosis.is_from_employer

    diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True)
    assert not diagnosis.is_from_employer
