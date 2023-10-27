from datetime import timedelta

from django.utils import timezone

from itou.employee_record.enums import NotificationStatus, Status
from itou.employee_record.models import EmployeeRecordBatch, EmployeeRecordUpdateNotification
from itou.employee_record.serializers import (
    EmployeeRecordUpdateNotificationBatchSerializer,
    EmployeeRecordUpdateNotificationSerializer,
    _AddressSerializer,
    _PersonSerializer,
)
from tests.employee_record.factories import EmployeeRecordFactory, EmployeeRecordWithProfileFactory
from tests.users.factories import JobSeekerFactory
from tests.utils.test import TestCase


class EmployeeRecordAddressSerializerTest(TestCase):
    def test_hexa_additional_address(self):
        # If additional address contains special characters
        # or is more than 32 charactrs long
        # then resulting additional address becomes `None`
        employee_record = EmployeeRecordWithProfileFactory(status=Status.PROCESSED)
        job_seeker = employee_record.job_seeker
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
        job_seeker = employee_record.job_seeker
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
        serializer = _AddressSerializer(JobSeekerFactory())

        assert serializer.data == {
            "adrTelephone": None,
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
    serializer = _PersonSerializer(
        EmployeeRecordFactory(job_application__job_seeker__jobseeker_profile__birth_country=None)
    )

    assert serializer.data["codeInseePays"] is None
    assert serializer.data["codeGroupePays"] is None


class EmployeeRecordUpdateNotificationSerializerTest(TestCase):
    def test_notification_serializer(self):
        # High-level : just check basic information
        start_at = timezone.localdate()
        end_at = timezone.localdate() + timedelta(weeks=52)
        employee_record = EmployeeRecordWithProfileFactory(status=Status.PROCESSED)
        approval = employee_record.approval
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

        personnal_data = data.get("personnePhysique")

        assert personnal_data is not None
        assert personnal_data.get("passIae") == employee_record.approval_number
        assert personnal_data.get("passDateDeb") == start_at.strftime("%d/%m/%Y")
        assert personnal_data.get("passDateFin") == end_at.strftime("%d/%m/%Y")

    def test_batch_serializer(self):
        # This is the same serializer used for employee record batches.
        # Previously not tested, killing 2 birds with 1 stone.

        start_at = timezone.localdate()
        end_at = timezone.localdate() + timedelta(weeks=52)

        # Add some EmployeeRecordUpdateNotification objects
        for idx in range(10):
            employee_record = EmployeeRecordWithProfileFactory(status=Status.PROCESSED)
            approval = employee_record.approval
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
            with self.subTest(idx):
                assert element.get("numLigne") == idx
                assert element.get("siret") is not None
                assert element.get("typeMouvement") == EmployeeRecordUpdateNotification.ASP_MOVEMENT_TYPE
