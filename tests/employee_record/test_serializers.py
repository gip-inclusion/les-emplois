from datetime import timedelta

import pytest
from django.utils import timezone

from itou.asp.models import AllocationDuration, Commune, EducationLevel, EITIContributions, SiaeMeasure
from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from itou.employee_record.enums import NotificationStatus, Status
from itou.employee_record.models import EmployeeRecordBatch, EmployeeRecordUpdateNotification
from itou.employee_record.serializers import (
    EmployeeRecordSerializer,
    EmployeeRecordUpdateNotificationBatchSerializer,
    EmployeeRecordUpdateNotificationSerializer,
    _AddressSerializer,
    _PersonSerializer,
    _SituationSerializer,
)
from tests.employee_record.factories import EmployeeRecordUpdateNotificationFactory, EmployeeRecordWithProfileFactory
from tests.users.factories import JobSeekerFactory


class TestEmployeeRecordPersonSerializer:
    def test_get_prenom(self):
        employee_record = EmployeeRecordWithProfileFactory(job_application__job_seeker__first_name="")
        job_seeker = employee_record.job_application.job_seeker
        serializer = _PersonSerializer(employee_record)

        assert serializer.get_prenom(employee_record) == ""

        job_seeker.first_name = "Jean"
        assert serializer.get_prenom(employee_record) == "JEAN"

        job_seeker.first_name = "Jean-Philippe"
        assert serializer.get_prenom(employee_record) == "JEAN-PHILIPPE"

        job_seeker.first_name = "Jean-Philippe René"
        assert serializer.get_prenom(employee_record) == "JEAN-PHILIPPE RENE"

        job_seeker.first_name = "Jean-Philippe René Hippolyte Gilbert Dufaël"
        assert serializer.get_prenom(employee_record) == "JEAN-PHILIPPE RENE HIPPOLYTE"


class TestEmployeeRecordAddressSerializer:
    def test_hexa_additional_address(self):
        # If additional address contains special characters
        # or is more than 32 charactrs long
        # then resulting additional address becomes `None`
        employee_record = EmployeeRecordWithProfileFactory(status=Status.PROCESSED)
        job_seeker = employee_record.job_application.job_seeker
        profile = job_seeker.jobseeker_profile
        profile.hexa_additional_address = "Bad additional address with %$£"

        serializer = _AddressSerializer(job_seeker)
        data = serializer.data

        assert data is not None
        assert data["adrCpltDistribution"] is None

        profile.hexa_additional_address = "Bad additional address because it is really over 32 characters"
        serializer = _AddressSerializer(job_seeker)
        data = serializer.data

        assert data is not None
        assert data["adrCpltDistribution"] is None

        good_address = "Good additional address"
        profile.hexa_additional_address = good_address

        serializer = _AddressSerializer(job_seeker)
        data = serializer.data

        assert data is not None
        assert good_address == data["adrCpltDistribution"]

    def test_hexa_lane_name(self):
        # If lane name contains parens,
        # then remove them from resulting lane name
        # (better geolocation)
        employee_record = EmployeeRecordWithProfileFactory(status=Status.PROCESSED)
        job_seeker = employee_record.job_application.job_seeker
        profile = job_seeker.jobseeker_profile
        profile.hexa_lane_name = "Lane name (with parens)"

        serializer = _AddressSerializer(job_seeker)
        data = serializer.data

        assert data is not None
        assert "Lane name with parens" == data["adrLibelleVoie"]

        good_lane_name = "Lane name without parens"
        profile.hexa_lane_name = good_lane_name
        serializer = _AddressSerializer(job_seeker)
        data = serializer.data

        assert data is not None
        assert good_lane_name == data["adrLibelleVoie"]

    def test_with_empty_fields(self):
        commune = Commune.objects.order_by("?").first()
        serializer = _AddressSerializer(JobSeekerFactory(jobseeker_profile__hexa_commune=commune))

        assert serializer.data == {
            "adrTelephone": None,
            "adrMail": None,
            "adrNumeroVoie": None,
            "codeextensionvoie": None,
            "codetypevoie": "",
            "adrLibelleVoie": "",
            "adrCpltDistribution": None,
            "codeinseecom": commune.code,
            "codepostalcedex": "",
        }


class TestEmployeeRecordUpdateNotificationSerializer:
    def test_notification_serializer(self):
        # High-level : just check basic information
        start_at = timezone.localdate()
        end_at = timezone.localdate() + timedelta(weeks=52)
        employee_record = EmployeeRecordWithProfileFactory(status=Status.PROCESSED)
        approval = employee_record.job_application.approval
        approval.start_at = start_at
        approval.end_at = end_at
        employee_record.save()

        notification = EmployeeRecordUpdateNotification(employee_record=employee_record)
        serializer = EmployeeRecordUpdateNotificationSerializer(notification)
        data = serializer.data

        assert data is not None
        assert data.get("siret") == employee_record.siret
        assert data.get("mesure") == employee_record.asp_siae_type
        assert data.get("typeMouvement") == EmployeeRecordUpdateNotification.ASP_MOVEMENT_TYPE

        personal_data = data.get("personnePhysique")

        assert personal_data is not None
        assert personal_data.get("passIae") == employee_record.approval_number
        assert personal_data.get("passDateDeb") == start_at.strftime("%d/%m/%Y")
        assert personal_data.get("passDateFin") == end_at.strftime("%d/%m/%Y")

    def test_batch_serializer(self, subtests):
        # This is the same serializer used for employee record batches.
        # Previously not tested, killing 2 birds with 1 stone.

        start_at = timezone.localdate()
        end_at = timezone.localdate() + timedelta(weeks=52)

        # Add some EmployeeRecordUpdateNotification objects
        for idx in range(10):
            employee_record = EmployeeRecordWithProfileFactory(status=Status.PROCESSED)
            approval = employee_record.job_application.approval
            approval.start_at = start_at
            approval.end_at = end_at
            employee_record.save()
            EmployeeRecordUpdateNotification(
                employee_record=employee_record,
                asp_batch_line_number=idx,
            ).save()

        new_notifications = EmployeeRecordUpdateNotification.objects.filter(status=NotificationStatus.NEW)

        batch = EmployeeRecordBatch(new_notifications)
        data = EmployeeRecordUpdateNotificationBatchSerializer(batch).data

        assert data is not None

        elements = data.get("lignesTelechargement")

        assert len(new_notifications) == len(elements)
        for idx, element in enumerate(elements, 1):
            with subtests.test(idx):
                assert element.get("numLigne") == idx
                assert element.get("siret") is not None
                assert element.get("typeMouvement") == EmployeeRecordUpdateNotification.ASP_MOVEMENT_TYPE


@pytest.mark.parametrize(
    "field,value,key",
    [
        ("birth_country", None, "personnePhysique"),
        ("birth_place", None, "personnePhysique"),
        ("hexa_lane_type", "", "adresse"),
        ("hexa_lane_name", "", "adresse"),
        ("hexa_post_code", "", "adresse"),
        ("hexa_commune", None, "adresse"),
        ("education_level", "", "situationSalarie"),
    ],
)
def test_update_notification_use_static_serializers_on_missing_fields(snapshot, field, value, key):
    notification = EmployeeRecordUpdateNotificationFactory(
        employee_record__job_application__for_snapshot=True,
        **{f"employee_record__job_application__job_seeker__jobseeker_profile__{field}": value},
    )

    data = EmployeeRecordUpdateNotificationSerializer(notification).data
    assert data[key] == snapshot()


def test_update_notification_use_static_serializers_on_missing_pole_emploi_since_fields(snapshot):
    notification = EmployeeRecordUpdateNotificationFactory(
        employee_record__job_application__for_snapshot=True,
        employee_record__job_application__job_seeker__jobseeker_profile__pole_emploi_id="1234567U",
        employee_record__job_application__job_seeker__jobseeker_profile__pole_emploi_since="",
    )

    data = EmployeeRecordUpdateNotificationSerializer(notification).data
    assert data["situationSalarie"] == snapshot()


@pytest.mark.parametrize(
    "field,value",
    [
        ("mean_monthly_income_before_process", None),
        ("mean_monthly_income_before_process", 0.0),
        ("actor_met_for_business_creation", ""),
    ],
)
def test_update_notification_use_static_serializers_on_missing_eiti_fields(snapshot, field, value):
    factory_profile_path = "employee_record__job_application__job_seeker__jobseeker_profile"
    notification = EmployeeRecordUpdateNotificationFactory(
        employee_record__job_application__for_snapshot=True,
        employee_record__job_application__to_company__kind=CompanyKind.EITI,
        **{
            f"{factory_profile_path}__actor_met_for_business_creation": "Actor Étude",
            f"{factory_profile_path}__mean_monthly_income_before_process": 12345.67,
            f"{factory_profile_path}__{field}": value,
        },
    )

    data = EmployeeRecordUpdateNotificationSerializer(notification).data
    assert data["situationSalarie"] == snapshot()


@pytest.mark.parametrize("kind", Company.ASP_EMPLOYEE_RECORD_KINDS)
def test_situation_salarie_serializer_with_empty_fields(snapshot, kind):
    employee_record = EmployeeRecordWithProfileFactory(
        status=Status.PROCESSED,
        job_application__to_company__kind=kind,
        job_application__job_seeker__jobseeker_profile__education_level="",
    )
    notification = EmployeeRecordUpdateNotification(employee_record=employee_record)

    data = EmployeeRecordSerializer(employee_record).data
    assert data["mesure"] == SiaeMeasure.from_siae_kind(kind)
    assert data["situationSalarie"] == snapshot(name="employee record")

    data = EmployeeRecordUpdateNotificationSerializer(notification).data
    assert data["mesure"] == SiaeMeasure.from_siae_kind(kind)
    assert data["situationSalarie"] == snapshot(name="employee record update notification")


@pytest.mark.parametrize("kind", Company.ASP_EMPLOYEE_RECORD_KINDS)
def test_situation_salarie_serializer_with_eiti_fields_filled(snapshot, kind):
    employee_record = EmployeeRecordWithProfileFactory(
        status=Status.PROCESSED,
        job_application__to_company__kind=kind,
        # EITI fields
        job_application__job_seeker__jobseeker_profile__oeth_employee=True,
        job_application__job_seeker__jobseeker_profile__are_allocation_since=AllocationDuration.LESS_THAN_6_MONTHS,
        job_application__job_seeker__jobseeker_profile__activity_bonus_since=AllocationDuration.FROM_6_TO_11_MONTHS,
        job_application__job_seeker__jobseeker_profile__cape_freelance=True,
        job_application__job_seeker__jobseeker_profile__cesa_freelance=True,
        job_application__job_seeker__jobseeker_profile__actor_met_for_business_creation="Actor Étude",
        job_application__job_seeker__jobseeker_profile__mean_monthly_income_before_process=12345.67,
        job_application__job_seeker__jobseeker_profile__eiti_contributions=EITIContributions.OTHER_SERVICES,
        # Force some fields for snapshots
        job_application__job_seeker__jobseeker_profile__education_level=EducationLevel.NO_SCHOOLING,
    )
    notification = EmployeeRecordUpdateNotification(employee_record=employee_record)

    data = EmployeeRecordSerializer(employee_record).data
    assert data["mesure"] == SiaeMeasure.from_siae_kind(kind)
    assert data["situationSalarie"] == snapshot(name="employee record")

    data = EmployeeRecordUpdateNotificationSerializer(notification).data
    assert data["mesure"] == SiaeMeasure.from_siae_kind(kind)
    assert data["situationSalarie"] == snapshot(name="employee record update notification")


@pytest.mark.parametrize("pole_emploi_id", ["1234567A", "12345678912", ""])
def test_situation_salarie_serializer_pole_emploi_id(snapshot, pole_emploi_id):
    pole_emploi_since = AllocationDuration.FROM_6_TO_11_MONTHS if pole_emploi_id else ""
    employee_record = EmployeeRecordWithProfileFactory(
        status=Status.PROCESSED,
        job_application__job_seeker__for_snapshot=True,
        job_application__job_seeker__jobseeker_profile__pole_emploi_id=pole_emploi_id,
        job_application__job_seeker__jobseeker_profile__pole_emploi_since=pole_emploi_since,
    )

    data = _SituationSerializer(employee_record).data
    assert data == snapshot
