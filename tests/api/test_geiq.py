import io
import logging
import uuid
from unittest.mock import patch

import pytest
from django.urls import reverse
from freezegun import freeze_time
from rest_framework.test import APIClient

from itou.api.geiq import serializers
from itou.api.geiq.views import GeiqApiAnonymousUser
from itou.api.models import CompanyToken
from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from itou.eligibility.enums import AdministrativeCriteriaKind
from itou.eligibility.models.geiq import GEIQAdministrativeCriteria
from tests.companies.factories import CompanyFactory
from tests.job_applications.factories import JobApplicationFactory, PriorActionFactory
from tests.users.factories import ItouStaffFactory, JobSeekerFactory
from tests.utils.test import assertSnapshotQueries


def _api_client():
    client = APIClient()
    user = GeiqApiAnonymousUser()
    client.force_authenticate(user=user)
    return client


def _api_token_for(companies):
    token = CompanyToken(label="test")
    token.save()
    for company in companies:
        token.companies.add(company)
    return token


def test_candidatures_geiq_token_authentication():
    TOKEN_KEY = "00000000-bf01-45d8-adf6-2706d83c78bd"
    token = CompanyToken(label="test-token", key=TOKEN_KEY)
    token.save()

    geiq = CompanyFactory(siret="11832575900001", kind=CompanyKind.GEIQ)
    antenna = CompanyFactory(siret="11832575900037", kind=CompanyKind.GEIQ, source=Company.SOURCE_USER_CREATED)
    token.companies.add(geiq)

    JobApplicationFactory(state="accepted", to_company=geiq)
    JobApplicationFactory(state="accepted", to_company=antenna)

    api_client = APIClient(headers={"Authorization": "Token invalid"})
    response = api_client.get(reverse("v1:geiq_jobapplication_list"))
    assert response.status_code == 401

    # try with an unknown UUID token
    api_client = APIClient(headers={"Authorization": "Token 72da817e-f000-4fa3-a2b2-119883410698"})
    response = api_client.get(reverse("v1:geiq_jobapplication_list"))
    assert response.status_code == 401

    # returns any associated antennas even if the token is not linked to it explicitly
    api_client = APIClient(headers={"Authorization": f"Token {TOKEN_KEY}"})
    response = api_client.get(reverse("v1:geiq_jobapplication_list"))
    assert response.status_code == 200
    assert response.json()["count"] == 2
    assert response.json()["results"][0]["siret_employeur"] == "11832575900001"
    assert response.json()["results"][1]["siret_employeur"] == "11832575900037"


def test_candidatures_geiq_api_authentication(client):
    user = ItouStaffFactory(is_superuser=False)
    client.force_login(user)
    response = client.get(reverse("v1:geiq_jobapplication_list"))
    assert response.status_code == 403

    user.is_superuser = True
    user.save()
    response = client.get(reverse("v1:geiq_jobapplication_list"))
    assert response.status_code == 200


@pytest.mark.parametrize(
    "job_application_status",
    ["new", "processing", "postponed", "prior_to_hire", "refused", "cancelled", "obsolete"],
)
def test_candidatures_geiq_is_empty(snapshot, job_application_status):
    client = _api_client()

    ja = JobApplicationFactory(
        with_geiq_eligibility_diagnosis=True,
        state=job_application_status,
    )
    _api_token_for([ja.to_company])
    response = client.get(reverse("v1:geiq_jobapplication_list"))
    assert response.status_code == 200
    assert response.json() == snapshot(name="empty")


@freeze_time("2023-07-21")
def test_candidatures_geiq_nominal(snapshot):
    client = _api_client()

    response = client.get(reverse("v1:geiq_jobapplication_list"))
    assert response.status_code == 200
    assert response.json() == snapshot(name="empty")

    job_seeker = JobSeekerFactory(for_snapshot=True, jobseeker_profile__education_level="51")

    job_application = JobApplicationFactory(
        pk=uuid.UUID("bf657b69-3245-430c-b461-09c6792b9504"),
        sent_by_authorized_prescriber_organisation=True,
        with_geiq_eligibility_diagnosis=True,
        was_hired=True,
        to_company__romes=["N1101"],
        job_seeker=job_seeker,
        sender_kind="prescriber",
        sender_prescriber_organization__kind="HUDA",
        to_company__siret="11832575900001",
        to_company__kind=CompanyKind.GEIQ,
        prehiring_guidance_days=42,
        contract_type="PROFESSIONAL_TRAINING",
        nb_hours_per_week=47,
        qualification_type="CQP",
        qualification_level="NOT_RELEVANT",
        planned_training_hours=1664,
        inverted_vae_contract=True,
    )

    JobApplicationFactory(
        pk=uuid.UUID("bf657b69-3245-430c-b461-09c6792b9505"),
        with_geiq_eligibility_diagnosis_from_prescriber=True,
        was_hired=True,
        to_company__romes=["N1101"],
        job_seeker=job_seeker,
        to_company__siret="11832575966666",  # same SIREN, different SIRET
        to_company__kind=CompanyKind.GEIQ,
        prehiring_guidance_days=28,
        contract_type="APPRENTICESHIP",
        nb_hours_per_week=35,
        qualification_type="CCN",
        qualification_level="LEVEL_3",
        planned_training_hours=12,
        inverted_vae_contract=False,
    )

    _api_token_for([job_application.to_company])

    # professional experience
    PriorActionFactory(job_application=job_application, action="PROFESSIONAL_SITUATION_EXPERIENCE_PMSMP")
    # prequalification
    PriorActionFactory(job_application=job_application, action="PREQUALIFICATION_AFPR")

    crit = GEIQAdministrativeCriteria.objects.get(kind=AdministrativeCriteriaKind.JEUNE)
    job_seeker.geiq_eligibility_diagnoses.first().administrative_criteria.add(crit)

    with assertSnapshotQueries(snapshot(name="SQL queries without filter")):
        response = client.get(reverse("v1:geiq_jobapplication_list"))
    assert response.status_code == 200
    assert response.json() == snapshot(name="with_results")

    with assertSnapshotQueries(snapshot(name="SQL queries without result")):
        response = client.get(f"{reverse('v1:geiq_jobapplication_list')}?siren=foobar")
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid SIREN."}

    with assertSnapshotQueries(snapshot(name="SQL queries with result")):
        response = client.get(f"{reverse('v1:geiq_jobapplication_list')}?siren={job_application.to_company.siren}")
    assert response.status_code == 200
    assert response.json()["count"] == 2  # returns the antenna as well


def test_serializer_method_defaults():
    ja = JobApplicationFactory(
        with_geiq_eligibility_diagnosis=False,
        job_seeker__jobseeker_profile__education_level="",
    )
    serializer = serializers.GeiqJobApplicationSerializer()
    assert serializer.get_criteres_eligibilite(ja) == []
    assert serializer.get_niveau_formation(ja) is None


@pytest.mark.parametrize(
    "title,outcome",
    [("M", "H"), ("MME", "F"), ("FOO", None)],
)
def test_civilite_mapping(title, outcome):
    serializer = serializers.GeiqJobApplicationSerializer()
    ja = JobApplicationFactory.build(job_seeker__title=title)
    assert serializer.get_civilite(ja) == outcome


@pytest.mark.parametrize(
    "choices_class,mapping",
    [
        (serializers.LabelCivilite, serializers.EMPLOIS_TO_LABEL_CIVILITE),
        (serializers.LabelContractType, serializers.EMPLOIS_TO_LABEL_CONTRACT_TYPE),
        (serializers.LabelDiagAuthorKind, serializers.EMPLOIS_TO_LABEL_DIAG_AUTHOR_KIND),
        (serializers.LabelEducationLevel, serializers.ASP_TO_LABEL_EDUCATION_LEVELS),
        (serializers.LabelEducationLevel, serializers.EMPLOIS_TO_LABEL_QUALIFICATION_LEVEL),
        (serializers.LabelPrequalification, serializers.EMPLOIS_TO_LABEL_PREQUALIFICATION),
        (serializers.LabelProfessionalSituationExperience, serializers.EMPLOIS_TO_LABEL_PRO_SITU_EXP),
        (serializers.LabelQualificationType, serializers.EMPLOIS_TO_LABEL_QUALIFICATION_TYPE),
    ],
)
def test_label_mappings(choices_class, mapping):
    assert set(choices_class.values) == set(mapping.values())


@freeze_time("2023-07-21")
def test_criteres_eligibilite():
    job_application = JobApplicationFactory(
        with_geiq_eligibility_diagnosis=True,
        was_hired=True,
    )
    serializer = serializers.GeiqJobApplicationSerializer()
    assert serializer.get_criteres_eligibilite(job_application) == []

    # Some criteria aren't relevant for a GEIQ diagnosis and aren't advertised in our API
    pe_crit = GEIQAdministrativeCriteria.objects.get(slug="personne-inscrite-a-pole-emploi")
    job_application.geiq_eligibility_diagnosis.administrative_criteria.add(pe_crit)
    assert serializer.get_criteres_eligibilite(job_application) == []

    # Other criteria can either add 1 code
    rsa_crit = GEIQAdministrativeCriteria.objects.get(slug="beneficiaire-du-rsa")
    job_application.geiq_eligibility_diagnosis.administrative_criteria.add(rsa_crit)
    assert serializer.get_criteres_eligibilite(job_application) == ["RSA"]

    # Or 2 codes
    zrr_crit = GEIQAdministrativeCriteria.objects.get(slug="resident-zrr")
    job_application.geiq_eligibility_diagnosis.administrative_criteria.add(zrr_crit)
    assert serializer.get_criteres_eligibilite(job_application) == ["QPV/ZRR", "RSA", "ZRR"]


def test_log_token_datadog_info():
    token = CompanyToken.objects.create(label="test-token")
    api_client = APIClient(headers={"Authorization": f"Token {token.key}"})

    root_logger = logging.getLogger()
    stream_handler = root_logger.handlers[0]
    assert isinstance(stream_handler, logging.StreamHandler)
    with io.StringIO() as captured:
        # caplog cannot be used since the organization_id is written by the log formatter
        # capsys/capfd did not want to work because https://github.com/pytest-dev/pytest/issues/5997
        with patch.object(stream_handler, "stream", captured):
            response = api_client.get(reverse("v1:geiq_jobapplication_list"))
        assert response.status_code == 200
        # Check that the organization_id is properly logged to stdout
        assert f'"token": "CompanyToken-{token.pk}"' in captured.getvalue()
