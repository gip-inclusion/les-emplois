import datetime
import io
import re

import pytest
from django.core.management import call_command
from django.utils import timezone

from itou.employee_record import models
from itou.employee_record.enums import Status
from itou.employee_record.management.commands import sanitize_employee_records
from tests.employee_record import factories
from tests.users.factories import JobSeekerProfileFactory


@pytest.fixture(name="command")
def command_fixture():
    return sanitize_employee_records.Command(stdout=io.StringIO(), stderr=io.StringIO())


def test_handle_dry_run(mocker, command, caplog):
    mocker.patch.object(command, "_check_approvals")
    mocker.patch.object(command, "_check_missed_notifications")

    command.handle(wet_run=False)
    assert caplog.messages == [
        "Command launched with wet_run=False",
        "Checking employee records coherence before transferring to ASP",
        "Employee records sanitizing done. Have a great day!",
        "Setting transaction to be rollback as wet_run=False",
    ]


def test_missing_approvals(command, caplog):
    # Check for employee record without approval (through job application)

    employee_record = factories.EmployeeRecordFactory()
    employee_record.job_application.approval = None
    employee_record.job_application.save()

    command.handle(wet_run=True)

    assert models.EmployeeRecord.objects.count() == 0
    assert caplog.messages == [
        "Checking employee records coherence before transferring to ASP",
        "found 1 employee records with missing approval",
        "deleted 1/1 employee records with missing approval",
        "found 0 missed employee records notifications",
        "0/0 employee records were unarchived",
        "Employee records sanitizing done. Have a great day!",
    ]
    assert not models.EmployeeRecord.objects.filter(pk=employee_record.pk).exists()


def test_missed_notifications(command, faker, caplog, snapshot):
    # Approval() with watched_data_updated_at are what we want
    employee_record_with_watched_data_updated_at = factories.EmployeeRecordFactory(
        status=models.Status.ARCHIVED,
        watched_data_updated_at=timezone.now(),
    )

    # But not Approval() without watched_data_updated_at
    factories.EmployeeRecordFactory(
        status=models.Status.ARCHIVED,
        watched_data_updated_at=None,
    )

    # Approval() that can no longer be prolonged are ignored, even with watched_data_updated_at
    factories.EmployeeRecordFactory(
        status=models.Status.ARCHIVED,
        watched_data_updated_at=timezone.now(),
        job_application__approval__expired=True,
        job_application__approval__created_at=faker.future_datetime(tzinfo=datetime.UTC),
    )

    # Various cases are now set up, finally check the behavior
    command.handle(wet_run=True)
    assert employee_record_with_watched_data_updated_at.update_notifications.count() == 0  # No notification created
    employee_record_with_watched_data_updated_at.refresh_from_db()
    assert employee_record_with_watched_data_updated_at.status != Status.ARCHIVED
    assert [re.sub(r"<EmployeeRecord: .+?>", "[EMPLOYEE RECORD]", msg) for msg in caplog.messages] == snapshot()


def test_missed_notifications_limit(mocker, snapshot, command, caplog):
    mocker.patch.object(command, "MAX_MISSED_NOTIFICATIONS_CREATED", 2)
    factories.EmployeeRecordFactory.create_batch(
        3,
        status=models.Status.ARCHIVED,
        watched_data_updated_at=timezone.now(),
    )

    command.handle(wet_run=True)

    assert models.EmployeeRecordUpdateNotification.objects.count() == 0  # No notification created
    assert [re.sub(r"<EmployeeRecord: .+?>", "[EMPLOYEE RECORD]", msg) for msg in caplog.messages] == snapshot()


def test_handle_3437_errors():
    expected_label = (
        "Un salarié existe déjà pour cette structure avec un identifiant Plate-forme de l'inclusion différent. ({})"
    )
    new_asp_uid_OK = "1234567890abcdef1234567890abcd"
    employee_record_OK = factories.EmployeeRecordFactory(
        ready_for_transfer=True,  # Make sure all the infos needed for ready transition are here
        status=models.Status.REJECTED,
        asp_processing_code=models.EmployeeRecord.ASP_UNIQUE_ID_MISMATCH_CODE,
        asp_processing_label=expected_label.format(new_asp_uid_OK),
    )
    new_asp_uid_OK_but_not_ready = "111111111111111111111111111111"
    employee_record_OK_but_not_ready = factories.EmployeeRecordFactory(
        status=models.Status.REJECTED,
        asp_processing_code=models.EmployeeRecord.ASP_UNIQUE_ID_MISMATCH_CODE,
        asp_processing_label=expected_label.format(new_asp_uid_OK_but_not_ready),
    )
    employee_record_wrong_log = factories.EmployeeRecordFactory(
        status=models.Status.REJECTED,
        asp_processing_code=models.EmployeeRecord.ASP_UNIQUE_ID_MISMATCH_CODE,
        asp_processing_label="Unexpected label",
    )
    invalid_asp_uid = "1234567890abcdef"
    employee_record_invalid_asp_uid = factories.EmployeeRecordFactory(
        status=models.Status.REJECTED,
        asp_processing_code=models.EmployeeRecord.ASP_UNIQUE_ID_MISMATCH_CODE,
        asp_processing_label=expected_label.format(invalid_asp_uid),
    )
    duplicate_asp_uid = JobSeekerProfileFactory().asp_uid
    employee_record_duplicate_asp_uid = factories.EmployeeRecordFactory(
        status=models.Status.REJECTED,
        asp_processing_code=models.EmployeeRecord.ASP_UNIQUE_ID_MISMATCH_CODE,
        asp_processing_label=expected_label.format(duplicate_asp_uid),
    )
    previous_asp_uid = {
        employee_record.pk: employee_record.job_application.job_seeker.jobseeker_profile.asp_uid
        for employee_record in [
            employee_record_OK,
            employee_record_OK_but_not_ready,
            employee_record_wrong_log,
            employee_record_invalid_asp_uid,
            employee_record_duplicate_asp_uid,
        ]
    }
    call_command("sanitize_employee_records", wet_run=True)

    employee_record_OK.job_application.job_seeker.jobseeker_profile.refresh_from_db()
    assert (
        employee_record_OK.job_application.job_seeker.jobseeker_profile.asp_uid
        != previous_asp_uid[employee_record_OK.pk]
    )
    assert employee_record_OK.job_application.job_seeker.jobseeker_profile.asp_uid == new_asp_uid_OK
    employee_record_OK.refresh_from_db()
    assert employee_record_OK.status == models.Status.READY

    employee_record_OK_but_not_ready.job_application.job_seeker.jobseeker_profile.refresh_from_db()
    assert (
        employee_record_OK_but_not_ready.job_application.job_seeker.jobseeker_profile.asp_uid
        != previous_asp_uid[employee_record_OK_but_not_ready.pk]
    )
    assert (
        employee_record_OK_but_not_ready.job_application.job_seeker.jobseeker_profile.asp_uid
        == new_asp_uid_OK_but_not_ready
    )
    employee_record_OK_but_not_ready.refresh_from_db()
    assert employee_record_OK_but_not_ready.status == models.Status.REJECTED

    for untouched_er in [
        employee_record_wrong_log,
        employee_record_invalid_asp_uid,
        employee_record_duplicate_asp_uid,
    ]:
        untouched_er.refresh_from_db()
        assert untouched_er.status == models.Status.REJECTED
        untouched_er.job_application.job_seeker.jobseeker_profile.refresh_from_db()
        assert untouched_er.job_application.job_seeker.jobseeker_profile.asp_uid == previous_asp_uid[untouched_er.pk]
