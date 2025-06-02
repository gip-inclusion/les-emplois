import json
import re
import uuid

import factory.fuzzy
import freezegun
import pytest
from django.test.utils import override_settings
from django.utils import timezone

from itou.employee_record.enums import NotificationStatus, Status
from itou.employee_record.management.commands import transfer_employee_records
from itou.employee_record.models import EmployeeRecordBatch
from itou.job_applications.enums import JobApplicationState
from itou.utils.asp import REMOTE_DOWNLOAD_DIR, REMOTE_UPLOAD_DIR
from tests.approvals.factories import ProlongationFactory, SuspensionFactory
from tests.employee_record.factories import EmployeeRecordFactory, EmployeeRecordUpdateNotificationFactory


@pytest.fixture(name="command")
def command_fixture(mocker, settings, sftp_directory, sftp_client_factory):
    # Set required settings
    settings.ASP_SFTP_HOST = "0.0.0.0"  # non-routable IP, just in case :)
    settings.ASP_SFTP_USER = "django_tests"

    # Setup directory
    sftp_directory.joinpath(REMOTE_UPLOAD_DIR).mkdir()
    sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR).mkdir()

    # Create the management command and mock the SFTP connection
    command = transfer_employee_records.Command()
    mocker.patch("itou.utils.asp.get_sftp_connection", sftp_client_factory)

    return command


def process_incoming_file(sftp_directory, code, message):
    for file in sftp_directory.joinpath(REMOTE_UPLOAD_DIR).iterdir():
        batch = json.loads(file.read_text())

        for employee_record in batch.get("lignesTelechargement", []):
            employee_record["codeTraitement"] = code
            employee_record["libelleTraitement"] = message

        feedback_file = sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR, EmployeeRecordBatch.feedback_filename(file.name))
        feedback_file.write_text(json.dumps(batch))


@override_settings(ASP_SFTP_HOST="")
def test_missing_environment_asp_sftp_host(snapshot, command, caplog):
    command.handle(upload=False, download=True, preflight=False, wet_run=False)
    assert caplog.messages == snapshot


def test_option_asp_test(snapshot, command, caplog):
    command.handle(asp_test=True, upload=False, download=True, preflight=False, wet_run=False)
    assert caplog.messages == snapshot


def test_connection_error(mocker, command, caplog):
    mocker.patch("itou.utils.asp.get_sftp_connection", side_effect=Exception)
    employee_record = EmployeeRecordFactory(ready_for_transfer=True)

    with pytest.raises(Exception):
        command.handle(upload=True, download=False, preflight=False, wet_run=True)

    employee_record.refresh_from_db()
    assert employee_record.status == Status.READY
    assert caplog.messages == []


def test_preflight(snapshot, command, caplog):
    EmployeeRecordFactory.create_batch(3, ready_for_transfer=True)

    command.handle(preflight=True, upload=False, download=False, wet_run=False)
    assert caplog.messages == snapshot


def test_preflight_without_object(snapshot, command, caplog):
    command.handle(preflight=True, upload=False, download=False, wet_run=False)
    assert caplog.messages == snapshot


def test_preflight_with_error(snapshot, command, caplog):
    EmployeeRecordFactory(
        ready_for_transfer=True,
        approval_number="",
        job_application__approval=None,
        # Data used by the snapshot
        pk=42,
        job_application__pk=uuid.UUID("49536a29-88b5-49c3-8c46-333bbbc36308"),
        job_application__to_company__siret="17483349486512",
        job_application__to_company__convention__asp_id="21",
        job_application__approval__number="XXXXX3724456",
        job_application__job_seeker__pk=4242,
    )

    command.handle(preflight=True, upload=False, download=False, wet_run=False)
    assert caplog.messages == snapshot


def test_preflight_without_an_accepted_job_application(caplog, snapshot, command):
    EmployeeRecordFactory(
        ready_for_transfer=True,
        job_application__state=factory.fuzzy.FuzzyChoice(
            set(JobApplicationState.values) - {JobApplicationState.ACCEPTED}
        ),
    )

    command.handle(preflight=True, upload=False, download=False, wet_run=False)
    assert caplog.messages == snapshot


@freezegun.freeze_time("2021-09-27")
def test_upload_file_error(faker, snapshot, sftp_directory, command, caplog):
    employee_record = EmployeeRecordFactory(ready_for_transfer=True)
    sftp_directory.joinpath(REMOTE_UPLOAD_DIR).rmdir()

    command.handle(upload=True, download=False, preflight=False, wet_run=True)

    employee_record.refresh_from_db()
    assert employee_record.status == Status.READY
    assert caplog.messages == snapshot


@freezegun.freeze_time("2021-09-27")
def test_upload_only_create_a_limited_number_of_files(mocker, snapshot, sftp_directory, command, caplog):
    mocker.patch.object(EmployeeRecordBatch, "MAX_EMPLOYEE_RECORDS", 1)
    EmployeeRecordFactory(pk=4321, ready_for_transfer=True)
    EmployeeRecordFactory(pk=1234, ready_for_transfer=True)

    command.handle(upload=True, download=False, preflight=False, wet_run=True)
    assert len(list(sftp_directory.joinpath(REMOTE_UPLOAD_DIR).iterdir())) == command.MAX_UPLOADED_FILES

    assert [
        re.sub(r"<EmployeeRecord: PK:1234 .+?>", "<EmployeeRecord pk=1234>", msg) for msg in caplog.messages
    ] == snapshot()


@freezegun.freeze_time("2021-09-27")
def test_upload_only_send_a_limited_number_of_rows(mocker, snapshot, sftp_directory, command):
    mocker.patch.object(EmployeeRecordBatch, "MAX_EMPLOYEE_RECORDS", 1)
    EmployeeRecordFactory.create_batch(2, ready_for_transfer=True)

    command.handle(upload=True, download=False, preflight=False, wet_run=True)
    for file in sftp_directory.joinpath(REMOTE_UPLOAD_DIR).iterdir():
        assert len(file.read_text().splitlines()) == 1


def test_upload_without_an_accepted_job_application(caplog, snapshot, command):
    EmployeeRecordFactory(
        ready_for_transfer=True,
        job_application__state=factory.fuzzy.FuzzyChoice(
            set(JobApplicationState.values) - {JobApplicationState.ACCEPTED}
        ),
    )

    command.handle(preflight=False, upload=True, download=False, wet_run=False)
    assert caplog.messages == snapshot


def test_download_file_error(faker, snapshot, sftp_directory, command, caplog):
    sftp_directory.joinpath("retrait/RIAE_FS_00000000000000_FichierRetour.json").touch(0o000)

    command.handle(upload=False, download=True, preflight=False, wet_run=True)
    assert caplog.messages == snapshot


@freezegun.freeze_time("2021-09-27")
def test_dry_run_upload_and_download(command):
    employee_record = EmployeeRecordFactory(ready_for_transfer=True)

    command.handle(upload=True, download=True, preflight=False, wet_run=False)
    employee_record.refresh_from_db()
    assert employee_record.status == Status.READY


@freezegun.freeze_time("2021-09-27")
def test_upload_and_download(snapshot, sftp_directory, command, caplog):
    employee_record = EmployeeRecordFactory(ready_for_transfer=True)

    command.handle(upload=True, download=False, preflight=False, wet_run=True)
    employee_record.refresh_from_db()
    assert employee_record.status == Status.SENT
    assert employee_record.asp_batch_line_number == 1
    assert employee_record.asp_batch_file is not None

    process_incoming_file(sftp_directory, "0000", "OK")

    command.handle(upload=False, download=True, preflight=False, wet_run=True)
    employee_record.refresh_from_db()
    assert employee_record.status == Status.PROCESSED
    assert employee_record.asp_processing_code == "0000"
    assert employee_record.archived_json.get("libelleTraitement") == "OK"

    assert [re.sub(r"<EmployeeRecord: .+?>", "[EMPLOYEE RECORD]", msg) for msg in caplog.messages] == snapshot()


def test_duplicates_automatic_processing(sftp_directory, command):
    employee_record = EmployeeRecordFactory(ready_for_transfer=True)

    command.handle(upload=True, download=False, preflight=False, wet_run=True)
    process_incoming_file(sftp_directory, "3436", "Duplicate")

    command.handle(upload=False, download=True, preflight=False, wet_run=True)
    employee_record.refresh_from_db()
    assert employee_record.status == Status.PROCESSED
    assert employee_record.asp_processing_code == "3436"
    assert employee_record.archived_json.get("libelleTraitement") == "Duplicate"
    assert employee_record.processed_as_duplicate is True


@pytest.mark.parametrize("extension_class", [ProlongationFactory, SuspensionFactory])
def test_duplicates_with_an_extension_generate_an_update_notification(sftp_directory, command, extension_class):
    employee_record = EmployeeRecordFactory(ready_for_transfer=True)
    extension_class(approval=employee_record.job_application.approval)

    command.handle(upload=True, download=False, preflight=False, wet_run=True)
    process_incoming_file(sftp_directory, "3436", "Duplicate")

    command.handle(upload=False, download=True, preflight=False, wet_run=True)
    assert employee_record.update_notifications.count() == 1
    assert employee_record.update_notifications.get().status == NotificationStatus.NEW


@pytest.mark.parametrize("status", set(NotificationStatus) - {NotificationStatus.NEW})
@pytest.mark.parametrize("extension_class", [ProlongationFactory, SuspensionFactory])
def test_duplicates_with_an_extension_generate_a_pristine_update_notification(
    sftp_directory, command, status, extension_class
):
    employee_record = EmployeeRecordFactory(ready_for_transfer=True)
    EmployeeRecordUpdateNotificationFactory(employee_record=employee_record, status=status)
    extension_class(approval=employee_record.job_application.approval)

    command.handle(upload=True, download=False, preflight=False, wet_run=True)
    process_incoming_file(sftp_directory, "3436", "Duplicate")

    command.handle(upload=False, download=True, preflight=False, wet_run=True)
    assert employee_record.update_notifications.count() == 2
    assert employee_record.update_notifications.latest("created_at").status == NotificationStatus.NEW


@pytest.mark.parametrize("extension_class", [ProlongationFactory, SuspensionFactory])
def test_duplicates_with_an_extension_update_the_existing_new_notification(sftp_directory, command, extension_class):
    employee_record = EmployeeRecordFactory(ready_for_transfer=True)
    EmployeeRecordUpdateNotificationFactory(employee_record=employee_record, status=NotificationStatus.NEW)
    extension_class(approval=employee_record.job_application.approval)

    command.handle(upload=True, download=False, preflight=False, wet_run=True)
    process_incoming_file(sftp_directory, "3436", "Duplicate")

    with freezegun.freeze_time():
        expected_updated_at = timezone.now()
        command.handle(upload=False, download=True, preflight=False, wet_run=True)
    assert employee_record.update_notifications.count() == 1
    notification = employee_record.update_notifications.get()
    assert notification.status == NotificationStatus.NEW
    assert notification.updated_at == expected_updated_at
