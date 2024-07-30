from datetime import timedelta

import pytest
from django.utils import timezone
from pytest_django.asserts import assertQuerySetEqual

from itou.employee_record.enums import NotificationStatus, Status
from itou.employee_record.models import EmployeeRecord, EmployeeRecordUpdateNotification
from tests.approvals.factories import ApprovalFactory, ProlongationFactory, SuspensionFactory
from tests.employee_record.factories import EmployeeRecordFactory


class TestEmployeeRecordUpdateNotification:
    def test_update_approval_start_date(self):
        # If a modification occurs on the `start_date` field of an approval linked to a processed employee record
        # then exactly *one* 'NEW' notification objects must be created.
        # A normal case
        employee_record = EmployeeRecordFactory(status=Status.PROCESSED)
        approval = employee_record.job_application.approval
        today = timezone.localdate()

        approval.start_at = today + timedelta(days=1)
        approval.save()

        assert 1 == EmployeeRecord.objects.count()
        assert today + timedelta(days=1) == approval.start_at
        assert 1 == EmployeeRecordUpdateNotification.objects.filter(status=NotificationStatus.NEW).count()

    def test_update_approval_end_date(self):
        # If a modification occurs on the `end_date` field of an approval linked to a processed employee record
        # then exactly *one* 'NEW' notification objects must be created.
        # Another normal case
        employee_record = EmployeeRecordFactory(status=Status.PROCESSED)
        approval = employee_record.job_application.approval
        today = timezone.localdate()

        approval.end_at = today + timedelta(days=2)
        approval.save()

        assert 1 == EmployeeRecord.objects.count()
        assert today + timedelta(days=2) == approval.end_at
        assert 1 == EmployeeRecordUpdateNotification.objects.filter(status=NotificationStatus.NEW).count()

    def test_update_approval_twice(self):
        # If SEVERAL modifications occurs on a monitored field of an approval linked to a processed employee record
        # then exactly *one* 'NEW' notification objects must be created,
        # (which is the last one)
        employee_record = EmployeeRecordFactory(status=Status.PROCESSED)
        approval = employee_record.job_application.approval
        today = timezone.localdate()

        approval.start_at = today + timedelta(days=1)
        approval.save()

        assert 1 == EmployeeRecord.objects.count()
        assert today + timedelta(days=1) == approval.start_at
        assert 1 == EmployeeRecordUpdateNotification.objects.filter(status=NotificationStatus.NEW).count()

        approval.start_at = today
        approval.save()

        assert today == approval.start_at
        assert 1 == EmployeeRecordUpdateNotification.objects.filter(status=NotificationStatus.NEW).count()

    def test_update_non_monitored_fields(self):
        # If a modification occurs on an approval linked to any or no employee record,
        # And the target fields are not monitored
        # Then there is no creation of an EmployeeRecordUpdateNotification object.
        employee_record = EmployeeRecordFactory(status=Status.PROCESSED)
        approval = employee_record.job_application.approval

        approval.created_at = timezone.localtime()
        approval.save()

        assert 1 == EmployeeRecord.objects.count()
        assert 0 == EmployeeRecordUpdateNotification.objects.filter(status=NotificationStatus.NEW).count()

    def test_update_on_approval_without_linked_employee_record(self):
        # If a date modification occurs on an approval NOT linked to any employee record,
        # then no notification object must be created.
        approval = ApprovalFactory()
        today = timezone.localdate()

        approval.end_at = today + timedelta(days=2)
        approval.save()

        assert 0 == EmployeeRecordUpdateNotification.objects.filter(status=NotificationStatus.NEW).count()

    @pytest.mark.parametrize("status", [elt for elt in Status.values if elt != Status.PROCESSED])
    def test_update_on_non_processed_employee_record(self, status):
        # If a date modification occurs on an approval linked to an employee record NOT in processed state,
        # then no notification object must be created.
        employee_record = EmployeeRecordFactory(status=status)
        approval = employee_record.job_application.approval
        today = timezone.localtime()

        approval.created_at = today + timedelta(days=2)
        approval.save()

        assert 0 == EmployeeRecordUpdateNotification.objects.filter(status=NotificationStatus.NEW).count()

    def test_update_on_multiple_employee_records(self):
        # If a date modification occurs on an approval linked to *N* processed employee record,
        # then *N* 'NEW' notification objects must be created.
        employee_record_1 = EmployeeRecordFactory(status=Status.PROCESSED)
        employee_record_2 = EmployeeRecordFactory(status=Status.PROCESSED)
        approval = employee_record_1.job_application.approval

        employee_record_2.job_application.approval = approval
        # Trigger join is made on `approval_number`,
        # and factory boy does not magically update this field.
        employee_record_2.approval_number = approval.number
        employee_record_2.save()

        approval.end_at = timezone.localdate() + timedelta(days=2)
        approval.save()

        assertQuerySetEqual(
            EmployeeRecordUpdateNotification.objects.filter(status=NotificationStatus.NEW),
            [employee_record_1.pk, employee_record_2.pk],
            transform=lambda notif: notif.employee_record_id,
            ordered=False,
        )

    def test_update_with_suspension(self):
        # Creation of a suspension on an approval linked to an employee record
        # must also create a new employee record update notification.
        employee_record = EmployeeRecordFactory(status=Status.PROCESSED)
        approval = employee_record.job_application.approval
        start_at = timezone.localdate()

        SuspensionFactory(
            approval=approval,
            start_at=start_at,
        )

        assert 1 == EmployeeRecordUpdateNotification.objects.filter(status=NotificationStatus.NEW).count()
        assert employee_record.pk == EmployeeRecordUpdateNotification.objects.earliest("created_at").employee_record.pk

    def test_update_with_prolongation(self):
        # Creation of a prolongation on an approval linked to an employee record
        # must also create a new employee record update notification.
        employee_record = EmployeeRecordFactory(status=Status.PROCESSED)
        approval = employee_record.job_application.approval

        ProlongationFactory(
            approval=approval,
            start_at=approval.end_at,
        )

        assert 1 == EmployeeRecordUpdateNotification.objects.filter(status=NotificationStatus.NEW).count()
        assert employee_record.pk == EmployeeRecordUpdateNotification.objects.earliest("created_at").employee_record.pk
