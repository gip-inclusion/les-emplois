from datetime import timedelta

import pytest
from django.utils import timezone

from itou.api.employee_record_api.serializers import (
    EmployeeRecordAPISerializer,
    EmployeeRecordUpdateNotificationAPISerializer,
    _API_AddressSerializer,
    _API_PersonSerializer,
)
from itou.asp.models import Commune, Country, SiaeMeasure
from itou.companies.models import Company
from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecordUpdateNotification
from tests.employee_record.factories import EmployeeRecordFactory, EmployeeRecordWithProfileFactory
from tests.users.factories import JobSeekerFactory


def test_address_serializer_hexa_additional_address():
    # If additional address contains special characters or is more than 32 characters long
    # then resulting additional address becomes `None`
    employee_record = EmployeeRecordWithProfileFactory(status=Status.PROCESSED)
    job_seeker = employee_record.job_application.job_seeker
    profile = job_seeker.jobseeker_profile
    profile.hexa_additional_address = "Bad additional address with %$£"

    serializer = _API_AddressSerializer(job_seeker)
    data = serializer.data

    assert data is not None
    assert data["adrCpltDistribution"] is None

    profile.hexa_additional_address = "Bad additional address because it is really over 32 characters"
    serializer = _API_AddressSerializer(job_seeker)
    data = serializer.data

    assert data is not None
    assert data["adrCpltDistribution"] is None

    good_address = "Good additional address"
    profile.hexa_additional_address = good_address

    serializer = _API_AddressSerializer(job_seeker)
    data = serializer.data

    assert data is not None
    assert good_address == data["adrCpltDistribution"]


def test_address_serializer_hexa_lane_name():
    # If lane name contains parens,
    # then remove them from resulting lane name
    # (better geolocation)
    employee_record = EmployeeRecordWithProfileFactory(status=Status.PROCESSED)
    job_seeker = employee_record.job_application.job_seeker
    profile = job_seeker.jobseeker_profile
    profile.hexa_lane_name = "Lane name (with parens)"

    serializer = _API_AddressSerializer(job_seeker)
    data = serializer.data

    assert data is not None
    assert "Lane name with parens" == data["adrLibelleVoie"]

    good_lane_name = "Lane name without parens"
    profile.hexa_lane_name = good_lane_name
    serializer = _API_AddressSerializer(job_seeker)
    data = serializer.data

    assert data is not None
    assert good_lane_name == data["adrLibelleVoie"]


def test_address_serializer_with_empty_fields():
    serializer = _API_AddressSerializer(JobSeekerFactory(phone="", email=None))

    assert serializer.data == {
        "adrTelephone": "",
        "adrMail": None,
        "adrNumeroVoie": "",
        "codeextensionvoie": None,
        "codetypevoie": "",
        "adrLibelleVoie": None,
        "adrCpltDistribution": None,
        "codeinseecom": None,
        "codepostalcedex": "",
    }


class TestApiPersonSerializerBirthPlace:
    def test_person_serializer_with_empty_birth_country(self):
        serializer = _API_PersonSerializer(
            EmployeeRecordFactory(job_application__job_seeker__jobseeker_profile__birth_country=None)
        )

        assert serializer.data["codeInseePays"] is None
        assert serializer.data["codeGroupePays"] is None

    def test_person_serializer_birth_place(self):
        commune = Commune.objects.filter(code="86194").first()
        france = Country.objects.get(pk=Country.FRANCE_ID)
        employee_record = EmployeeRecordWithProfileFactory(
            job_application__job_seeker__jobseeker_profile__birth_place=commune,
            job_application__job_seeker__jobseeker_profile__birth_country_id=france.id,
        )
        serialized = _API_PersonSerializer(employee_record).data
        assert serialized["codeInseePays"] == france.code
        assert serialized["codeComInsee"] == {
            "codeDpt": "086",
            "codeComInsee": "86194",
        }

    def test_person_serializer_birth_place_in_nouvelle_caledonie(self):
        noumea_commune = Commune.objects.get(code="98818")
        noumea_country = Country.objects.get(name="NOUMEA")
        employee_record = EmployeeRecordWithProfileFactory(
            job_application__job_seeker__jobseeker_profile__birth_place=noumea_commune,
            job_application__job_seeker__jobseeker_profile__birth_country_id=Country.FRANCE_ID,
        )
        serialized = _API_PersonSerializer(employee_record).data
        assert serialized["codeInseePays"] == noumea_country.code
        assert serialized["codeComInsee"] == {
            "codeDpt": "099",
            "codeComInsee": None,
        }

    def test_person_serializer_birth_place_in_foreign_country(self):
        denmark = Country.objects.get(name="DANEMARK")
        employee_record = EmployeeRecordWithProfileFactory(
            job_application__job_seeker__jobseeker_profile__birth_place=None,
            job_application__job_seeker__jobseeker_profile__birth_country=denmark,
        )
        serialized = _API_PersonSerializer(employee_record).data
        assert serialized["codeInseePays"] == denmark.code
        assert serialized["codeComInsee"] == {
            "codeDpt": "099",
            "codeComInsee": None,
        }


@pytest.mark.parametrize(
    "nir,ntt,expected",
    [
        pytest.param("", None, "", id="empty"),
        pytest.param("123456789012345", "12345678901", "123456789012345", id="nir_and_ntt"),
        pytest.param("", "12345678901", "12345678901", id="ntt_only"),
        pytest.param("723456789012345", "12345678901", "12345678901", id="ntt_required_by_nia"),
    ],
)
def test_person_serializer_nir_and_ntt_related_fields(nir, ntt, expected):
    employee_record = EmployeeRecordFactory(
        ntt=ntt,
        job_application__job_seeker__jobseeker_profile__nir=nir,
    )

    serializer = _API_PersonSerializer(employee_record)
    assert serializer.data["NIR"] == nir
    assert serializer.data["NTT"] == ntt
    assert serializer.data["salarieNIR"] == expected


@pytest.mark.parametrize("kind", Company.ASP_EMPLOYEE_RECORD_KINDS)
def test_oeth_employee(kind):
    employee_record = EmployeeRecordWithProfileFactory(
        status=Status.PROCESSED,
        job_application__to_company__kind=kind,
    )
    employee_record.job_application.job_seeker.jobseeker_profile.oeth_employee = True
    data = EmployeeRecordAPISerializer(employee_record).data

    assert data["mesure"] == SiaeMeasure.from_siae_kind(kind)
    assert data["situationSalarie"]["salarieOETH"] is True


def test_notification_serializer():
    # High-level: check basic information
    start_at = timezone.localdate()
    end_at = timezone.localdate() + timedelta(weeks=52)
    employee_record = EmployeeRecordWithProfileFactory(status=Status.PROCESSED)
    approval = employee_record.job_application.approval
    approval.start_at = start_at
    approval.end_at = end_at
    employee_record.save()

    data = EmployeeRecordUpdateNotificationAPISerializer(
        EmployeeRecordUpdateNotification(employee_record=employee_record)
    ).data
    assert data is not None
    assert data.get("siret") == employee_record.siret
    assert data.get("mesure") == employee_record.asp_measure
    assert data.get("typeMouvement") == EmployeeRecordUpdateNotification.ASP_MOVEMENT_TYPE

    personal_data = data.get("personnePhysique")
    assert personal_data is not None
    assert personal_data.get("passIae") == employee_record.approval_number
    assert personal_data.get("passDateDeb") == start_at.strftime("%d/%m/%Y")
    assert personal_data.get("passDateFin") == end_at.strftime("%d/%m/%Y")
