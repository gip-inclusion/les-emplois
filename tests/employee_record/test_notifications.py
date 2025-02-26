import random
from datetime import timedelta

import pytest
from django.utils import timezone

from itou.employee_record.enums import NotificationStatus, Status
from itou.employee_record.models import EmployeeRecordUpdateNotification
from tests.approvals.factories import ApprovalFactory, ProlongationFactory, SuspensionFactory
from tests.employee_record.factories import EmployeeRecordFactory


@pytest.mark.parametrize("status", [Status.PROCESSED, Status.SENT, Status.DISABLED])
@pytest.mark.parametrize("field", ["start_at", "end_at"])
def test_update_approval_monitored_field(field, status):
    # If one or more modifications occurs on a monitored field of an approval
    # linked to an employee record with a wanted status,
    # then exactly *one* 'NEW' notification objects must be created.
    employee_record = EmployeeRecordFactory(status=status)
    approval = employee_record.job_application.approval

    setattr(approval, field, timezone.localdate() + timedelta(days=1))
    approval.save()
    assert employee_record.update_notifications.filter(status=NotificationStatus.NEW).count() == 1

    setattr(approval, field, timezone.localdate() + timedelta(days=2))
    approval.save()
    assert employee_record.update_notifications.filter(status=NotificationStatus.NEW).count() == 1


@pytest.mark.parametrize("status", [Status.PROCESSED, Status.SENT, Status.DISABLED])
def test_update_approval_non_monitored_field(status):
    # If a modification occurs on an approval linked to an employee record with a wanted status,
    # and the target fields are not monitored,
    # then there is no creation of an EmployeeRecordUpdateNotification object.
    employee_record = EmployeeRecordFactory(status=status)
    approval = employee_record.job_application.approval

    approval.created_at = timezone.localtime()
    approval.save()
    assert not employee_record.update_notifications.exists()


@pytest.mark.parametrize("field", ["start_at", "end_at"])
def test_update_approval_monitored_field_without_employee_record(field):
    # If a modification occurs on an approval NOT linked to an employee record,
    # then no notification object must be created.
    approval = ApprovalFactory()

    setattr(approval, field, timezone.localdate() + timedelta(days=2))
    approval.save()
    assert not EmployeeRecordUpdateNotification.objects.exists()


@pytest.mark.parametrize("status", set(Status) - {Status.PROCESSED, Status.SENT, Status.DISABLED})
@pytest.mark.parametrize("field", ["start_at", "end_at"])
def test_update_approval_monitored_field_with_unwanted_status_employee_record(field, status):
    # If a modification occurs on an approval linked to an employee record NOT in a wanted state,
    # then no notification object must be created.
    employee_record = EmployeeRecordFactory(status=status)
    approval = employee_record.job_application.approval

    setattr(approval, field, timezone.localdate() + timedelta(days=2))
    approval.save()
    assert not EmployeeRecordUpdateNotification.objects.exists()


def test_update_approval_monitored_field_with_multiple_employee_records():
    # If a modification occurs on an approval linked to *N* employee records in a wanted status,
    # then *N* 'NEW' notification objects must be created.
    an_employee_record = EmployeeRecordFactory(status=random.choice([Status.PROCESSED, Status.SENT, Status.DISABLED]))
    approval = an_employee_record.job_application.approval
    another_employee_record = EmployeeRecordFactory(
        status=random.choice([Status.PROCESSED, Status.SENT, Status.DISABLED]),
        job_application__approval=approval,
    )

    setattr(approval, random.choice(["start_at", "end_at"]), timezone.localdate() + timedelta(days=2))
    approval.save()
    assert an_employee_record.update_notifications.filter(status=NotificationStatus.NEW).count() == 1
    assert another_employee_record.update_notifications.filter(status=NotificationStatus.NEW).count() == 1


@pytest.mark.parametrize("status", [Status.PROCESSED, Status.SENT, Status.DISABLED])
@pytest.mark.parametrize("factory", [ProlongationFactory, SuspensionFactory])
def test_update_with_approval_extension(factory, status):
    # Creation of a suspension or prolongation on an approval linked to an employee record
    # must also create a new employee record update notification.
    employee_record = EmployeeRecordFactory(status=status)
    factory(approval=employee_record.job_application.approval)

    assert employee_record.update_notifications.filter(status=NotificationStatus.NEW).count() == 1
