from datetime import timedelta

import pytest
from django.utils import timezone

from itou.api.employee_record_api.serializers import (
    EmployeeRecordAPISerializer,
    EmployeeRecordUpdateNotificationAPISerializer,
    _API_AddressSerializer,
    _API_PersonSerializer,
)
from itou.asp.models import SiaeMeasure
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


def test_person_serializer_with_empty_birth_country():
    serializer = _API_PersonSerializer(
        EmployeeRecordFactory(job_application__job_seeker__jobseeker_profile__birth_country=None)
    )

    assert serializer.data["codeInseePays"] is None
    assert serializer.data["codeGroupePays"] is None


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
    assert data.get("mesure") == employee_record.asp_siae_type
    assert data.get("typeMouvement") == EmployeeRecordUpdateNotification.ASP_MOVEMENT_TYPE

    personnal_data = data.get("personnePhysique")
    assert personnal_data is not None
    assert personnal_data.get("passIae") == employee_record.approval_number
    assert personnal_data.get("passDateDeb") == start_at.strftime("%d/%m/%Y")
    assert personnal_data.get("passDateFin") == end_at.strftime("%d/%m/%Y")
