import pytest
from django.contrib import messages
from django.contrib.admin import helpers
from django.urls import reverse
from pytest_django.asserts import assertContains, assertMessages

from itou.employee_record import models
from tests.employee_record import factories


def test_schedule_approval_update_notification_when_notification_do_not_exists(admin_client):
    employee_record = factories.BareEmployeeRecordFactory()

    response = admin_client.post(
        reverse("admin:employee_record_employeerecord_changelist"),
        {
            "action": "schedule_approval_update_notification",
            helpers.ACTION_CHECKBOX_NAME: [employee_record.pk],
        },
    )
    notification = models.EmployeeRecordUpdateNotification.objects.latest("created_at")
    assert notification.employee_record == employee_record
    assert notification.status == models.Status.NEW
    assertMessages(response, [messages.Message(messages.SUCCESS, "1 notification planifiée")])


def test_schedule_approval_update_notification_when_new_notification_already_exists(admin_client):
    notification = factories.BareEmployeeRecordUpdateNotificationFactory(status=models.Status.NEW)
    save_updated_at = notification.updated_at

    response = admin_client.post(
        reverse("admin:employee_record_employeerecord_changelist"),
        {
            "action": "schedule_approval_update_notification",
            helpers.ACTION_CHECKBOX_NAME: [notification.employee_record.pk],
        },
    )
    notification.refresh_from_db()
    assert notification.updated_at > save_updated_at
    assertMessages(response, [messages.Message(messages.SUCCESS, "1 notification mise à jour")])


@pytest.mark.parametrize("status", [status for status in models.Status if status != models.Status.NEW])
def test_schedule_approval_update_notification_when_other_than_new_notification_already_exists(admin_client, status):
    notification = factories.BareEmployeeRecordUpdateNotificationFactory(status=status)
    save_updated_at = notification.updated_at

    response = admin_client.post(
        reverse("admin:employee_record_employeerecord_changelist"),
        {
            "action": "schedule_approval_update_notification",
            helpers.ACTION_CHECKBOX_NAME: [notification.employee_record.pk],
        },
    )
    notification.refresh_from_db()
    assert notification.updated_at == save_updated_at
    created_notification = models.EmployeeRecordUpdateNotification.objects.latest("created_at")
    assert created_notification != notification
    assert created_notification.employee_record == notification.employee_record
    assert created_notification.status == models.Status.NEW
    assertMessages(response, [messages.Message(messages.SUCCESS, "1 notification planifiée")])


def test_job_seeker_profile_from_employee_record(admin_client):
    er = factories.EmployeeRecordFactory()
    job_seeker = er.job_application.job_seeker
    employee_record_view_url = reverse("admin:employee_record_employeerecord_change", args=[er.pk])
    response = admin_client.get(employee_record_view_url)
    assertContains(response, "Profil salarié")
    assertContains(response, job_seeker.jobseeker_profile.pk)
