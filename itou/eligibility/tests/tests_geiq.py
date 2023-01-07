import pytest
from django.core.exceptions import ValidationError

from itou.eligibility.enums import AdministrativeCriteriaAnnex, AdministrativeCriteriaLevel
from itou.eligibility.factories import GEIQEligibilityDiagnosisFactory
from itou.eligibility.models import GEIQAdministrativeCriteria, GEIQEligibilityDiagnosis
from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from itou.siaes.enums import SiaeKind
from itou.siaes.factories import SiaeWithMembershipAndJobsFactory
from itou.users.factories import JobSeekerFactory


@pytest.fixture
def administrative_criteria_annex_1():
    return GEIQAdministrativeCriteria.objects.get(pk=19)


@pytest.fixture
def administrative_criteria_annex_2_level_1():
    return GEIQAdministrativeCriteria.objects.get(pk=1)


@pytest.fixture
def administrative_criteria_annex_2_level_2():
    return GEIQAdministrativeCriteria.objects.get(pk=5)


def test_create_geiq_eligibility_diagnosis(administrative_criteria_annex_1):
    prescriber_org = PrescriberOrganizationWithMembershipFactory()
    geiq = SiaeWithMembershipAndJobsFactory(kind=SiaeKind.GEIQ)
    job_seeker = JobSeekerFactory()

    # good cop:

    # Default kind : IAE eligibility diagnosis
    diagnosis = GEIQEligibilityDiagnosis.create_eligibility_diagnosis(
        job_seeker=job_seeker,
        author_structure=prescriber_org,
        author=prescriber_org.members.first(),
    )

    assert diagnosis.pk

    diagnosis = GEIQEligibilityDiagnosis.create_eligibility_diagnosis(
        job_seeker=job_seeker,
        author_structure=geiq,
        author=geiq.members.first(),
    )

    assert diagnosis.pk

    diagnosis = GEIQEligibilityDiagnosis.create_eligibility_diagnosis(
        job_seeker=job_seeker,
        author_structure=geiq,
        author=geiq.members.first(),
        administrative_criteria=[administrative_criteria_annex_1],
    )

    assert diagnosis.pk

    # bad cop:

    # Author is SIAE, not GEIQ
    siae = SiaeWithMembershipAndJobsFactory(kind=SiaeKind.EI)
    with pytest.raises(ValueError):
        GEIQEligibilityDiagnosis.create_eligibility_diagnosis(
            job_seeker=job_seeker,
            author_structure=siae,
            author=siae.members.first(),
        )


def test_geiq_eligibility_diagnosis_validation():
    diagnosis = GEIQEligibilityDiagnosisFactory(with_geiq=True)
    diagnosis.clean()

    diagnosis = GEIQEligibilityDiagnosisFactory(with_prescriber=True)
    diagnosis.clean()

    # Only prescriber org or GEIQ are possible authors
    diagnosis.author_geiq = SiaeWithMembershipAndJobsFactory(kind=SiaeKind.EI)
    with pytest.raises(ValidationError):
        diagnosis.clean()

    # Contraint: both author kinds are not allowed
    with pytest.raises(
        ValidationError, match="Le diagnostic d'éligibilité GEIQ ne peut avoir 2 structures pour auteur"
    ):
        GEIQEligibilityDiagnosis(
            author_geiq=SiaeWithMembershipAndJobsFactory(kind=SiaeKind.GEIQ),
            author_prescriber_organization=PrescriberOrganizationWithMembershipFactory(),
        ).full_clean()


def test_geiq_administrative_criteria_validation(
    administrative_criteria_annex_1,
    administrative_criteria_annex_2_level_1,
    administrative_criteria_annex_2_level_2,
):
    # GEIQ diagnosis can be created with all kind of administrative criteria
    diagnosis = GEIQEligibilityDiagnosisFactory(with_geiq=True)
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


def test_geiq_eligibility_diagnosis_allowance_and_eligibility(
    administrative_criteria_annex_1,
    administrative_criteria_annex_2_level_1,
):
    a2l2_crits = GEIQAdministrativeCriteria.objects.filter(
        annex=AdministrativeCriteriaAnnex.ANNEX_2,
        level=AdministrativeCriteriaLevel.LEVEL_2,
    )[:2]
    diagnosis = GEIQEligibilityDiagnosisFactory(with_prescriber=True)

    # Prescriber author gets it all
    assert (True, 1400) == diagnosis._get_eligibility_and_allowance_amount()

    diagnosis = GEIQEligibilityDiagnosisFactory(with_geiq=True)

    assert (False, 0) == diagnosis._get_eligibility_and_allowance_amount()

    diagnosis.administrative_criteria.add(a2l2_crits[0])

    # One A2L2 is not enough
    assert (False, 0) == diagnosis._get_eligibility_and_allowance_amount()

    # Two is ok
    diagnosis.administrative_criteria.add(a2l2_crits[1])
    assert (True, 1400) == diagnosis._get_eligibility_and_allowance_amount()

    # One L1 is enough to get max allowance
    diagnosis = GEIQEligibilityDiagnosisFactory(with_geiq=True)
    diagnosis.administrative_criteria.add(administrative_criteria_annex_2_level_1)

    assert (True, 1400) == diagnosis._get_eligibility_and_allowance_amount()

    diagnosis = GEIQEligibilityDiagnosisFactory(with_geiq=True)
    diagnosis.administrative_criteria.add(administrative_criteria_annex_1)

    assert (True, 814) == diagnosis._get_eligibility_and_allowance_amount()

    # Adding another criteria will max allowance
    diagnosis.administrative_criteria.add(administrative_criteria_annex_2_level_1)
    assert (True, 1400) == diagnosis._get_eligibility_and_allowance_amount()
