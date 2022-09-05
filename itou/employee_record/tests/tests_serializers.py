from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from itou.employee_record.enums import Status
from itou.employee_record.factories import EmployeeRecordWithProfileFactory
from itou.employee_record.models import EmployeeRecordBatch, EmployeeRecordUpdateNotification
from itou.employee_record.serializers import (
    EmployeeRecordUpdateNotificationBatchSerializer,
    EmployeeRecordUpdateNotificationSerializer,
    _AddressSerializer,
)


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

        self.assertIsNotNone(data)
        self.assertIsNone(data["adrCpltDistribution"])

        profile.hexa_additional_address = "Bad additional address because it is really over 32 characters"
        serializer = _AddressSerializer(job_seeker)
        data = serializer.data

        self.assertIsNotNone(data)
        self.assertIsNone(data["adrCpltDistribution"])

        good_address = "Good additional address"
        profile.hexa_additional_address = good_address

        serializer = _AddressSerializer(job_seeker)
        data = serializer.data

        self.assertIsNotNone(data)
        self.assertEqual(good_address, data["adrCpltDistribution"])

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

        self.assertIsNotNone(data)
        self.assertEqual("Lane name with parens", data["adrLibelleVoie"])

        good_lane_name = "Lane name without parens"
        profile.hexa_lane_name = good_lane_name
        serializer = _AddressSerializer(job_seeker)
        data = serializer.data

        self.assertIsNotNone(data)
        self.assertEqual(good_lane_name, data["adrLibelleVoie"])

    def test_null_hexa_commune_code(self):
        employee_record = EmployeeRecordWithProfileFactory(status=Status.PROCESSED)
        job_seeker = employee_record.job_seeker
        job_seeker.jobseeker_profile.hexa_commune = None
        job_seeker.jobseeker_profile.save(update_fields=["hexa_commune"])

        serializer = _AddressSerializer(job_seeker)
        data = serializer.data

        self.assertNotIn("codeinseecom", data.keys())


class EmployeeRecordUpdateNotificationSerializerTest(TestCase):
    def test_notification_serializer(self):
        # High-level : just check basic information
        start_at = timezone.now().date()
        end_at = timezone.now().date() + timedelta(weeks=52)
        employee_record = EmployeeRecordWithProfileFactory(status=Status.PROCESSED)
        approval = employee_record.approval
        approval.start_at = start_at
        approval.end_at = end_at
        employee_record.save()

        notification = EmployeeRecordUpdateNotification(employee_record=employee_record)
        serializer = EmployeeRecordUpdateNotificationSerializer(notification)
        data = serializer.data

        self.assertIsNotNone(data)
        self.assertEqual(data.get("siret"), employee_record.siret)
        self.assertEqual(data.get("mesure"), employee_record.asp_siae_type)
        self.assertEqual(data.get("typeMouvement"), EmployeeRecordUpdateNotification.ASP_MOVEMENT_TYPE)

        personnal_data = data.get("personnePhysique")

        self.assertIsNotNone(personnal_data)
        self.assertEqual(personnal_data.get("passIae"), employee_record.approval_number)
        self.assertEqual(personnal_data.get("passDateDeb"), start_at.strftime("%d/%m/%Y"))
        self.assertEqual(personnal_data.get("passDateFin"), end_at.strftime("%d/%m/%Y"))

    def test_batch_serializer(self):
        # This is the same serializer used for employee record batches.
        # Previously not tested, killing 2 birds with 1 stone.

        start_at = timezone.now().date()
        end_at = timezone.now().date() + timedelta(weeks=52)

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

        new_notifications = EmployeeRecordUpdateNotification.objects.new()

        batch = EmployeeRecordBatch(new_notifications)
        data = EmployeeRecordUpdateNotificationBatchSerializer(batch).data

        self.assertIsNotNone(data)

        elements = data.get("lignesTelechargement")

        self.assertEqual(len(new_notifications), len(elements))
        for idx, element in enumerate(elements, 1):
            with self.subTest(idx):
                self.assertEqual(element.get("numLigne"), idx)
                self.assertIsNotNone(element.get("siret"))
                self.assertEqual(element.get("typeMouvement"), EmployeeRecordUpdateNotification.ASP_MOVEMENT_TYPE)
