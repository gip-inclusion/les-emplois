import pytest
from django.contrib import messages
from django.contrib.admin import helpers
from django.contrib.auth.models import Permission
from django.urls import reverse
from pytest_django.asserts import assertContains, assertMessages, assertNotContains, assertRedirects

from itou.approvals.models import Approval
from itou.employee_record import models
from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord
from tests.employee_record import factories
from tests.employee_record.factories import EmployeeRecordFactory
from tests.users.factories import ItouStaffFactory
from tests.utils.testing import parse_response_to_soup, pretty_indented


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
    assert notification.status == models.NotificationStatus.NEW
    assertMessages(response, [messages.Message(messages.SUCCESS, "1 notification planifiée")])


def test_schedule_approval_update_notification_when_new_notification_already_exists(admin_client):
    notification = factories.BareEmployeeRecordUpdateNotificationFactory(status=models.NotificationStatus.NEW)
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


@pytest.mark.parametrize("status", set(models.NotificationStatus) - {models.NotificationStatus.NEW})
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
    assert created_notification.status == models.NotificationStatus.NEW
    assertMessages(response, [messages.Message(messages.SUCCESS, "1 notification planifiée")])


def test_job_seeker_profile_from_employee_record(admin_client):
    er = factories.EmployeeRecordFactory()
    job_seeker = er.job_application.job_seeker
    employee_record_view_url = reverse("admin:employee_record_employeerecord_change", args=[er.pk])
    response = admin_client.get(employee_record_view_url)
    assertContains(response, "Profil salarié")
    assertContains(response, job_seeker.jobseeker_profile.pk)


def test_approval_number_from_employee_record(admin_client):
    er = factories.EmployeeRecordFactory()
    approval_number = Approval.objects.get(number=er.approval_number)
    employee_record_view_url = reverse("admin:employee_record_employeerecord_change", args=[er.pk])
    approval_number_url = reverse("admin:approvals_approval_change", args=[approval_number.pk])
    response = admin_client.get(employee_record_view_url)
    assertContains(response, f'<a href="{approval_number_url}">{approval_number.number}</a>')


def test_employee_record_deletion(admin_client):
    er = factories.BareEmployeeRecordFactory()
    delete_url = reverse("admin:employee_record_employeerecord_delete", kwargs={"object_id": er.pk})
    # Check the delete page doesn't break
    response = admin_client.get(delete_url)
    assertContains(response, str(er))
    # Check the deletion is working
    response = admin_client.post(delete_url, {"post": "yes"})
    assertRedirects(response, reverse("admin:employee_record_employeerecord_changelist"))
    assert EmployeeRecord.objects.filter(pk=er.pk).count() == 0


def test_employee_record_deletion_with_notification(admin_client):
    ern = factories.BareEmployeeRecordUpdateNotificationFactory()
    delete_url = reverse("admin:employee_record_employeerecord_delete", kwargs={"object_id": ern.employee_record.pk})
    # Check the delete page doesn't break
    response = admin_client.get(delete_url)
    assertContains(response, str(ern))
    assertContains(response, str(ern.employee_record))
    # Check the deletion is working
    response = admin_client.post(delete_url, {"post": "yes"})
    assertRedirects(response, reverse("admin:employee_record_employeerecord_changelist"))
    assert EmployeeRecord.objects.filter(pk=ern.employee_record.pk).count() == 0


@pytest.mark.parametrize("status", Status)
def test_available_transitions(snapshot, client, status):
    superuser = ItouStaffFactory(is_superuser=True)
    rw_user = ItouStaffFactory(is_superuser=False)
    rw_user.user_permissions.add(Permission.objects.get(codename="change_employeerecord"))
    ro_user = ItouStaffFactory(is_superuser=False)
    ro_user.user_permissions.add(Permission.objects.get(codename="view_employeerecord"))

    employee_record = EmployeeRecordFactory(status=status)
    url = reverse("admin:employee_record_employeerecord_change", args=[employee_record.pk])

    for user in [superuser, rw_user]:
        client.force_login(user)
        response = client.get(url)
        if status not in {Status.READY, Status.SENT}:
            assert pretty_indented(parse_response_to_soup(response, "#employee-record-transitions")) == snapshot(
                name="actions"
            )
        else:
            assertNotContains(response, '<div class="submit-row" id="employee-record-transitions">')

    client.force_login(ro_user)
    response = client.get(url)
    assertNotContains(response, '<div class="submit-row" id="employee-record-transitions">')


@pytest.mark.parametrize("code", ["", "0000", "32##", "3436"])
def test_available_transitions_for_unarchive(faker, snapshot, admin_client, code):
    employee_record = EmployeeRecordFactory(status=Status.ARCHIVED, asp_processing_code=faker.numerify(code))

    response = admin_client.get(reverse("admin:employee_record_employeerecord_change", args=[employee_record.pk]))
    assert pretty_indented(parse_response_to_soup(response, "#employee-record-transitions")) == snapshot()
