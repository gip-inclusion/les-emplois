from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from itou.employee_record.enums import Status
from itou.employee_record.factories import EmployeeRecordWithProfileFactory
from itou.employee_record.models import EmployeeRecordBatch, EmployeeRecordUpdateNotification
from itou.employee_record.serializers import (
    EmployeeRecordUpdateNotificationBatchSerializer,
    EmployeeRecordUpdateNotificationSerializer,
)


class EmployeeRecordUpdateNotificationSerializerTest(TestCase):

    # Fixtures needed for EmployeeRecordWithProfileFactory

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
