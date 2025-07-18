import functools

import pytest
from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from itou.companies.enums import CompanyKind
from itou.eligibility.enums import (
    AdministrativeCriteriaAnnex,
    AdministrativeCriteriaLevel,
)
from itou.eligibility.models import GEIQAdministrativeCriteria, GEIQEligibilityDiagnosis
from itou.eligibility.utils import _criteria_for_display
from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.users.enums import UserKind
from itou.utils.mocks.api_particulier import RESPONSES, ResponseKind
from tests.companies.factories import CompanyFactory, CompanyWithMembershipAndJobsFactory
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberOrganizationFactory, PrescriberOrganizationWithMembershipFactory
from tests.users.factories import ItouStaffFactory, JobSeekerFactory


@pytest.fixture
def administrative_criteria_annex_1():
    return GEIQAdministrativeCriteria.objects.get(pk=19)


@pytest.fixture
def administrative_criteria_annex_2_level_1():
    return GEIQAdministrativeCriteria.objects.get(pk=1)


@pytest.fixture
def administrative_criteria_annex_2_level_2():
    return GEIQAdministrativeCriteria.objects.get(pk=5)


@pytest.fixture
def administrative_criteria_both_annexes():
    return GEIQAdministrativeCriteria.objects.get(pk=13)


@pytest.fixture
def new_geiq():
    return CompanyWithMembershipAndJobsFactory(kind=CompanyKind.GEIQ)


def test_create_geiq_eligibility_diagnosis(administrative_criteria_annex_1):
    prescriber_org = PrescriberOrganizationWithMembershipFactory()
    geiq = CompanyWithMembershipAndJobsFactory(kind=CompanyKind.GEIQ)

    # good cops:

    # Default kind : IAE eligibility diagnosis
    diagnosis = GEIQEligibilityDiagnosis.create_eligibility_diagnosis(
        job_seeker=JobSeekerFactory(),
        author_structure=prescriber_org,
        author=prescriber_org.members.first(),
    )

    assert diagnosis.pk
    group = FollowUpGroup.objects.get()
    assert group.beneficiary == diagnosis.job_seeker
    membership = FollowUpGroupMembership.objects.get(follow_up_group=group)
    assert membership.member == diagnosis.author
    assert membership.creator == diagnosis.author

    diagnosis = GEIQEligibilityDiagnosis.create_eligibility_diagnosis(
        job_seeker=JobSeekerFactory(),
        author_structure=geiq,
        author=geiq.members.first(),
        administrative_criteria=[administrative_criteria_annex_1],
    )

    assert diagnosis.pk
    group = FollowUpGroup.objects.exclude(pk=group.pk).get()  # Get the newer group
    assert group.beneficiary == diagnosis.job_seeker
    membership = FollowUpGroupMembership.objects.get(follow_up_group=group)
    assert membership.member == diagnosis.author
    assert membership.creator == diagnosis.author

    # bad cops:

    # Author is SIAE, not GEIQ
    company = CompanyWithMembershipAndJobsFactory(kind=CompanyKind.EI)
    with pytest.raises(
        ValueError,
        match="Impossible de créer un diagnostic GEIQ avec une structure de type",
    ):
        GEIQEligibilityDiagnosis.create_eligibility_diagnosis(
            job_seeker=JobSeekerFactory(),
            author_structure=company,
            author=company.members.first(),
        )

    with pytest.raises(
        ValueError,
        match="Un diagnostic effectué par un GEIQ doit avoir au moins un critère d'éligibilité",
    ):
        GEIQEligibilityDiagnosis.create_eligibility_diagnosis(
            job_seeker=JobSeekerFactory(),
            author_structure=geiq,
            author=geiq.members.first(),
            administrative_criteria=(),
        )


@pytest.mark.parametrize(
    "organization_factory",
    [
        pytest.param(functools.partial(CompanyFactory, kind=CompanyKind.GEIQ), id="CompanyFactory"),
        PrescriberOrganizationFactory,
    ],
)
def test_create_eligibility_diagnosis_certify_certifiable_criteria(mocker, organization_factory):
    criterion = GEIQAdministrativeCriteria.objects.certifiable().order_by("?").first()
    mocker.patch(
        "itou.utils.apis.api_particulier._request",
        return_value=RESPONSES[criterion.kind][ResponseKind.CERTIFIED],
    )
    organization = organization_factory(with_membership=True)

    diagnosis = GEIQEligibilityDiagnosis.create_eligibility_diagnosis(
        JobSeekerFactory(certifiable=True),
        author=organization.members.first(),
        author_structure=organization,
        administrative_criteria=[criterion],
    )
    [criterion] = _criteria_for_display(
        [diagnosis.selected_administrative_criteria.get()], hiring_start_at=timezone.localdate()
    )
    assert criterion.is_considered_certified is True


def test_update_geiq_eligibility_diagnosis(administrative_criteria_annex_1):
    # Updating nothing
    with pytest.raises(ValueError, match="Le diagnostic fourni n'est pas un diagnostic GEIQ"):
        GEIQEligibilityDiagnosis.update_eligibility_diagnosis(None, None, ())

    # Trying to update an expired diagnosis
    diagnosis = GEIQEligibilityDiagnosisFactory(from_prescriber=True, expired=True)
    with pytest.raises(ValueError, match="Impossible de modifier un diagnostic GEIQ expiré"):
        GEIQEligibilityDiagnosis.update_eligibility_diagnosis(diagnosis, diagnosis.author, administrative_criteria=())

    # correct update case:
    diagnosis = GEIQEligibilityDiagnosisFactory(from_prescriber=True)
    GEIQEligibilityDiagnosis.update_eligibility_diagnosis(
        diagnosis, diagnosis.author, [administrative_criteria_annex_1]
    )

    assert list(diagnosis.administrative_criteria.all()) == [administrative_criteria_annex_1]


def test_update_geiq_eligibility_diagnosis_author():
    diagnosis = GEIQEligibilityDiagnosisFactory(from_prescriber=True)
    other_user = ItouStaffFactory()
    GEIQEligibilityDiagnosis.update_eligibility_diagnosis(diagnosis, other_user, ())
    diagnosis.refresh_from_db()

    assert diagnosis.author == other_user


@pytest.mark.parametrize("from_kind", {UserKind.EMPLOYER, UserKind.PRESCRIBER})
def test_update_eligibility_diagnosis_certify_certifiable_criteria(mocker, from_kind):
    criterion = GEIQAdministrativeCriteria.objects.certifiable().order_by("?").first()
    mocker.patch(
        "itou.utils.apis.api_particulier._request",
        return_value=RESPONSES[criterion.kind][ResponseKind.CERTIFIED],
    )
    diagnosis = GEIQEligibilityDiagnosisFactory(job_seeker__certifiable=True, **{f"from_{from_kind}": True})

    GEIQEligibilityDiagnosis.update_eligibility_diagnosis(
        diagnosis, diagnosis.author, administrative_criteria=[criterion]
    )
    [criterion] = _criteria_for_display(
        [diagnosis.selected_administrative_criteria.get()], hiring_start_at=timezone.localdate()
    )
    assert criterion.is_considered_certified is True


def test_geiq_eligibility_diagnosis_validation():
    diagnosis = GEIQEligibilityDiagnosisFactory(from_employer=True)
    diagnosis.clean()

    diagnosis = GEIQEligibilityDiagnosisFactory(from_prescriber=True)
    diagnosis.clean()

    # Only prescriber org or GEIQ are possible authors
    diagnosis.author_geiq = CompanyWithMembershipAndJobsFactory(kind=CompanyKind.EI)
    with pytest.raises(ValidationError, match="L'auteur du diagnostic n'est pas un GEIQ"):
        diagnosis.clean()

    # Contraint: both author kinds are not allowed
    geiq = CompanyWithMembershipAndJobsFactory(kind=CompanyKind.GEIQ)

    with pytest.raises(
        ValidationError,
        match="La structure de l'auteur ne correspond pas à son type",
    ):
        GEIQEligibilityDiagnosis(
            author_geiq=geiq,
            job_seeker=JobSeekerFactory(),
            author_prescriber_organization=PrescriberOrganizationWithMembershipFactory(),
        ).full_clean()


def test_geiq_administrative_criteria_validation(
    administrative_criteria_annex_1,
    administrative_criteria_annex_2_level_1,
    administrative_criteria_annex_2_level_2,
):
    # GEIQ diagnosis can be created with all kind of administrative criteria
    diagnosis = GEIQEligibilityDiagnosisFactory(from_employer=True)
    diagnosis.administrative_criteria.set(
        [
            administrative_criteria_annex_1,
            administrative_criteria_annex_2_level_1,
            administrative_criteria_annex_2_level_2,
        ]
    )

    # Validation of GEIQ criteria (constraints):

    # bad

    error_msg = "Incohérence entre l'annexe du critère administratif et son niveau"

    with pytest.raises(ValidationError, match=error_msg):
        GEIQAdministrativeCriteria(
            annex=AdministrativeCriteriaAnnex.ANNEX_1,
            level=AdministrativeCriteriaLevel.LEVEL_1,
        ).full_clean()

    with pytest.raises(ValidationError, match=error_msg):
        GEIQAdministrativeCriteria(
            annex=AdministrativeCriteriaAnnex.ANNEX_1,
            level=AdministrativeCriteriaLevel.LEVEL_2,
        ).full_clean()

    with pytest.raises(ValidationError, match=error_msg):
        GEIQAdministrativeCriteria(
            annex=AdministrativeCriteriaAnnex.ANNEX_2,
            level=None,
        ).full_clean()

    # good
    GEIQAdministrativeCriteria(
        annex=AdministrativeCriteriaAnnex.ANNEX_1,
        level=None,
    ).clean()

    GEIQAdministrativeCriteria(
        annex=AdministrativeCriteriaAnnex.ANNEX_2,
        level=AdministrativeCriteriaLevel.LEVEL_1,
    ).clean()

    GEIQAdministrativeCriteria(
        annex=AdministrativeCriteriaAnnex.ANNEX_2,
        level=AdministrativeCriteriaLevel.LEVEL_2,
    ).clean()

    # Case of dual-annexes criteria
    GEIQAdministrativeCriteria(
        annex=AdministrativeCriteriaAnnex.BOTH_ANNEXES,
        level=AdministrativeCriteriaLevel.LEVEL_1,
    ).clean()

    GEIQAdministrativeCriteria(
        annex=AdministrativeCriteriaAnnex.BOTH_ANNEXES,
        level=AdministrativeCriteriaLevel.LEVEL_2,
    ).clean()

    GEIQAdministrativeCriteria(
        annex=AdministrativeCriteriaAnnex.BOTH_ANNEXES,
        level=None,
    ).clean()


GEIQ_ALLOWANCE_AMOUNT_1400 = 1400
GEIQ_ALLOWANCE_AMOUNT_814 = 814


def test_geiq_eligibility_diagnosis_allowance(
    administrative_criteria_annex_1,
    administrative_criteria_annex_2_level_1,
    administrative_criteria_annex_2_level_2,
    administrative_criteria_both_annexes,
):
    a2l2_crits = GEIQAdministrativeCriteria.objects.filter(
        annex=AdministrativeCriteriaAnnex.ANNEX_2,
        level=AdministrativeCriteriaLevel.LEVEL_2,
    )[:2]

    # Prescriber author gets it all
    diagnosis = GEIQEligibilityDiagnosisFactory(from_prescriber=True)
    assert diagnosis.allowance_amount == GEIQ_ALLOWANCE_AMOUNT_1400

    diagnosis = GEIQEligibilityDiagnosisFactory(from_employer=True)
    assert diagnosis.allowance_amount == 0

    # One A2L2 is not enough
    diagnosis.administrative_criteria.add(a2l2_crits[0])
    assert diagnosis.allowance_amount == 0

    # Two is ok
    diagnosis.administrative_criteria.add(a2l2_crits[1])
    assert diagnosis.allowance_amount == GEIQ_ALLOWANCE_AMOUNT_1400

    # One L1 is enough to get max allowance
    diagnosis = GEIQEligibilityDiagnosisFactory(from_employer=True)
    diagnosis.administrative_criteria.add(administrative_criteria_annex_2_level_1)
    assert diagnosis.allowance_amount == GEIQ_ALLOWANCE_AMOUNT_1400

    diagnosis = GEIQEligibilityDiagnosisFactory(from_employer=True)
    diagnosis.administrative_criteria.add(administrative_criteria_annex_1)
    assert diagnosis.allowance_amount == GEIQ_ALLOWANCE_AMOUNT_814

    # Adding another criteria will max allowance
    diagnosis.administrative_criteria.add(administrative_criteria_annex_2_level_1)
    assert diagnosis.allowance_amount == GEIQ_ALLOWANCE_AMOUNT_1400

    # Special case of dual-annex criteria:

    # Counts as Annex 1 criterion...
    diagnosis = GEIQEligibilityDiagnosisFactory(from_employer=True)
    diagnosis.administrative_criteria.add(administrative_criteria_both_annexes)
    assert diagnosis.allowance_amount == GEIQ_ALLOWANCE_AMOUNT_814

    # ... and also as Annex 2 Level 2 criterion
    diagnosis.administrative_criteria.add(administrative_criteria_annex_2_level_2)
    assert diagnosis.allowance_amount == GEIQ_ALLOWANCE_AMOUNT_1400


def test_create_duplicate_diagnosis_in_same_geiq():
    diagnosis = GEIQEligibilityDiagnosisFactory(from_employer=True)

    # Check for duplicates : *valid* diagnosis, with same author structure for the same job seeker
    # Should have been nice as a unique constraint but does not work as expected because of mutable timestamps
    with pytest.raises(ValidationError, match="Il existe déjà un diagnostic GEIQ valide pour "):
        GEIQEligibilityDiagnosisFactory(
            from_employer=True,
            author_geiq=diagnosis.author_geiq,
            job_seeker=diagnosis.job_seeker,
            author=diagnosis.author_geiq.members.first(),
        )


def test_invalidate_obsolete_diagnosis():
    # job seeker must have a hiring (accepted job application) in GEIQ of the diagnosis
    # and hiring must occur during validity period of the diagnosis
    job_application = JobApplicationFactory(with_geiq_eligibility_diagnosis=True)
    diagnosis_with_hiring = job_application.geiq_eligibility_diagnosis
    diagnosis_without_hiring = GEIQEligibilityDiagnosisFactory(
        from_employer=True, job_seeker=job_application.job_seeker
    )

    assert diagnosis_with_hiring.is_valid
    assert diagnosis_without_hiring.is_valid

    GEIQEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=job_application.job_seeker)

    diagnosis_with_hiring.refresh_from_db()
    diagnosis_without_hiring.refresh_from_db()

    assert diagnosis_with_hiring.is_valid
    assert not diagnosis_without_hiring.is_valid


# Check coherence with multiple GEIQ diagnosis done
# for the same job seeker with different authors (GEIQ perimeter)


def test_create_dup_geiq_eligibility_diagnosis_with_geiq_and_prescriber(new_geiq, administrative_criteria_annex_1):
    # Create a diagnosis with a prescriber author
    diagnosis = GEIQEligibilityDiagnosisFactory(from_prescriber=True)

    # If the diagnosis is valid, then new GEIQ authored diagnoses are not allowed
    with pytest.raises(ValidationError, match=r"Il existe déjà un diagnostic GEIQ valide"):
        GEIQEligibilityDiagnosis.create_eligibility_diagnosis(
            diagnosis.job_seeker,
            new_geiq.members.first(),
            new_geiq,
            (administrative_criteria_annex_1,),
        )

    # This perfectly ok if the prescriber diagnosis has expired
    diagnosis.expires_at -= relativedelta(months=7)
    diagnosis.save()

    assert GEIQEligibilityDiagnosis.create_eligibility_diagnosis(
        diagnosis.job_seeker,
        new_geiq.members.first(),
        new_geiq,
        (administrative_criteria_annex_1,),
    )


def test_create_dup_geiq_eligibility_diagnosis_with_two_geiq():
    # Creating duplicate GEIQ diagnosis with the same GEIQ and job seeker is not allowed
    geiq_diagnosis = GEIQEligibilityDiagnosisFactory(from_employer=True)

    with pytest.raises(
        ValidationError,
        match="Il existe déjà un diagnostic GEIQ valide pour cet utilisateur",
    ):
        GEIQEligibilityDiagnosisFactory(
            from_employer=True,
            author_geiq=geiq_diagnosis.author_geiq,
            job_seeker=geiq_diagnosis.job_seeker,
        )

    # It is possible if the other diagnosis is no longer valid
    geiq_diagnosis.expires_at -= relativedelta(months=7)
    geiq_diagnosis.save()

    assert GEIQEligibilityDiagnosisFactory(
        from_employer=True,
        author_geiq=geiq_diagnosis.author_geiq,
        job_seeker=geiq_diagnosis.job_seeker,
    )


def test_prescriber_geiq_diagnosis_priority():
    # If there are existing valid GEIQ diagnoses for the same job seeker and created by GEIQs,
    # they are automatically "expired" when a prescriber creates a new diagnosis (it has priority over GEIQ ones)
    # GEIQ diagnoses linked to a hiring are kept valid
    geiq_diagnosis = GEIQEligibilityDiagnosisFactory(from_employer=True)
    job_seeker = geiq_diagnosis.job_seeker
    geiq_diagnosis_with_hiring = GEIQEligibilityDiagnosisFactory(from_employer=True, job_seeker=job_seeker)
    JobApplicationFactory(
        with_geiq_eligibility_diagnosis=True,
        job_seeker=job_seeker,
        geiq_eligibility_diagnosis=geiq_diagnosis_with_hiring,
    )

    assert geiq_diagnosis.is_valid
    assert geiq_diagnosis_with_hiring.is_valid

    prescriber_diagnosis = GEIQEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=job_seeker)
    geiq_diagnosis.refresh_from_db()
    geiq_diagnosis_with_hiring.refresh_from_db()

    assert prescriber_diagnosis.is_valid
    assert not geiq_diagnosis.is_valid
    assert geiq_diagnosis_with_hiring.is_valid


def test_authored_by_prescriber_or_geiq():
    geiq_diagnosis_with_hiring = GEIQEligibilityDiagnosisFactory(from_employer=True)
    JobApplicationFactory(
        with_geiq_eligibility_diagnosis=True,
        geiq_eligibility_diagnosis=geiq_diagnosis_with_hiring,
    )
    prescriber_diagnosis = GEIQEligibilityDiagnosisFactory(
        from_prescriber=True,
        job_seeker=geiq_diagnosis_with_hiring.job_seeker,
    )

    valid_diagnoses = GEIQEligibilityDiagnosis.objects.authored_by_prescriber_or_geiq(
        geiq_diagnosis_with_hiring.author_geiq
    )

    assert {prescriber_diagnosis, geiq_diagnosis_with_hiring} == set(valid_diagnoses)


def test_diagnoses_for():
    geiq_diagnosis = GEIQEligibilityDiagnosisFactory(from_employer=True)
    job_seeker = geiq_diagnosis.job_seeker
    other_geiq_diagnosis = GEIQEligibilityDiagnosisFactory(from_employer=True, job_seeker=job_seeker)
    # Order matters
    prescriber_diagnosis = GEIQEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=job_seeker)

    # without specified GEIQ: authorized prescriber diagnoses only
    diagnoses_for = GEIQEligibilityDiagnosis.objects.diagnoses_for(job_seeker=job_seeker)
    assert list(diagnoses_for) == [prescriber_diagnosis]

    # with specified GEIQ: authorized prescriber first and that GEIQ diagnosis
    diagnoses_for = GEIQEligibilityDiagnosis.objects.diagnoses_for(
        job_seeker=job_seeker, for_geiq=geiq_diagnosis.author_geiq
    )
    assert list(diagnoses_for) == [prescriber_diagnosis, geiq_diagnosis]

    # with for_job_seeker=True: all diagnoses for that job seeker
    diagnoses_for = GEIQEligibilityDiagnosis.objects.diagnoses_for(
        job_seeker=job_seeker, for_geiq=geiq_diagnosis.author_geiq, for_job_seeker=True
    )
    assert list(diagnoses_for) == [prescriber_diagnosis, other_geiq_diagnosis, geiq_diagnosis]


def test_administrativecriteria_level_annex_consistency():
    # Sequences are not uptodate
    pk_max = GEIQAdministrativeCriteria.objects.aggregate(Max("pk"))["pk__max"]
    GEIQAdministrativeCriteria.objects.create(
        pk=pk_max + 1,
        name="Test",
        level=AdministrativeCriteriaLevel.LEVEL_1,
        annex=AdministrativeCriteriaAnnex.BOTH_ANNEXES,
    )

    # Annex 2 without level
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            GEIQAdministrativeCriteria.objects.create(
                pk=pk_max + 2, name="Test", level=None, annex=AdministrativeCriteriaAnnex.ANNEX_2
            )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            GEIQAdministrativeCriteria.objects.create(
                pk=pk_max + 3, name="Test", level=None, annex=AdministrativeCriteriaAnnex.BOTH_ANNEXES
            )

    # Level where not allowed
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            GEIQAdministrativeCriteria.objects.create(
                pk=pk_max + 4,
                name="Test",
                level=AdministrativeCriteriaLevel.LEVEL_1,
                annex=AdministrativeCriteriaAnnex.ANNEX_1,
            )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            GEIQAdministrativeCriteria.objects.create(
                pk=pk_max + 5,
                name="Test",
                level=AdministrativeCriteriaLevel.LEVEL_2,
                annex=AdministrativeCriteriaAnnex.NO_ANNEX,
            )
