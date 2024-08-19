import io
import json

import freezegun
import pytest
from django.test.utils import override_settings

from itou.employee_record.enums import Status
from itou.employee_record.management.commands import transfer_employee_records_updates
from itou.employee_record.models import EmployeeRecordBatch
from itou.utils.asp import REMOTE_DOWNLOAD_DIR, REMOTE_UPLOAD_DIR
from tests.employee_record.factories import EmployeeRecordUpdateNotificationFactory


@pytest.fixture(name="command")
def command_fixture(mocker, settings, sftp_directory, sftp_client_factory):
    # Set required settings
    settings.ASP_SFTP_HOST = "0.0.0.0"  # non-routable IP, just in case :)
    settings.ASP_SFTP_USER = "django_tests"

    # Setup directory
    sftp_directory.joinpath(REMOTE_UPLOAD_DIR).mkdir()
    sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR).mkdir()

    # Create the management command and mock the SFTP connection
    command = transfer_employee_records_updates.Command(stdout=io.StringIO(), stderr=io.StringIO())
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
def test_missing_environment_asp_sftp_host(snapshot, command):
    command.handle(upload=False, download=True, preflight=False, wet_run=False)
    assert command.stdout.getvalue() == snapshot


def test_option_asp_test(snapshot, command):
    command.handle(asp_test=True, upload=False, download=True, preflight=False, wet_run=False)
    assert command.stdout.getvalue() == snapshot


def test_connection_error(mocker, command):
    mocker.patch("itou.utils.asp.get_sftp_connection", side_effect=Exception)
    notification = EmployeeRecordUpdateNotificationFactory(ready_for_transfer=True)

    with pytest.raises(Exception):
        command.handle(upload=True, download=False, preflight=False, wet_run=True)

    notification.refresh_from_db()
    assert notification.status == Status.NEW
    assert command.stdout.getvalue() == ""


def test_preflight(snapshot, command):
    EmployeeRecordUpdateNotificationFactory.create_batch(3, ready_for_transfer=True)

    command.handle(preflight=True, upload=False, download=False, wet_run=False)
    assert command.stdout.getvalue() == snapshot


def test_preflight_without_object(snapshot, command):
    command.handle(preflight=True, upload=False, download=False, wet_run=False)
    assert command.stdout.getvalue() == snapshot


def test_preflight_with_error(snapshot, command):
    EmployeeRecordUpdateNotificationFactory(
        ready_for_transfer=True,
        employee_record__approval_number="",
        employee_record__job_application__approval=None,
        # Data used by the snapshot
        pk=42,
    )

    command.handle(preflight=True, upload=False, download=False, wet_run=False)
    assert command.stdout.getvalue() == snapshot


@freezegun.freeze_time("2021-09-27")
def test_upload_file_error(faker, snapshot, sftp_directory, command):
    notification = EmployeeRecordUpdateNotificationFactory(ready_for_transfer=True)
    sftp_directory.joinpath(REMOTE_UPLOAD_DIR).rmdir()

    command.handle(upload=True, download=False, preflight=False, wet_run=True)

    notification.refresh_from_db()
    assert notification.status == Status.NEW
    assert command.stdout.getvalue() == snapshot


@freezegun.freeze_time("2021-09-27")
def test_upload_only_create_a_limited_number_of_files(mocker, snapshot, sftp_directory, command):
    mocker.patch.object(EmployeeRecordBatch, "MAX_EMPLOYEE_RECORDS", 1)
    EmployeeRecordUpdateNotificationFactory.create_batch(2, ready_for_transfer=True)

    command.handle(upload=True, download=False, preflight=False, wet_run=True)
    assert len(list(sftp_directory.joinpath(REMOTE_UPLOAD_DIR).iterdir())) == command.MAX_UPLOADED_FILES

    assert command.stdout.getvalue() == snapshot


@freezegun.freeze_time("2021-09-27")
def test_upload_only_send_a_limited_number_of_rows(mocker, snapshot, sftp_directory, command):
    mocker.patch.object(EmployeeRecordBatch, "MAX_EMPLOYEE_RECORDS", 1)
    EmployeeRecordUpdateNotificationFactory.create_batch(2, ready_for_transfer=True)

    command.handle(upload=True, download=False, preflight=False, wet_run=True)
    for file in sftp_directory.joinpath(REMOTE_UPLOAD_DIR).iterdir():
        assert len(file.read_text().splitlines()) == 1


def test_download_file_error(faker, snapshot, sftp_directory, command):
    sftp_directory.joinpath("retrait/RIAE_FS_00000000000000_FichierRetour.json").touch(0o000)

    command.handle(upload=False, download=True, preflight=False, wet_run=True)
    assert command.stdout.getvalue() == snapshot


@freezegun.freeze_time("2021-09-27")
def test_dry_run_upload_and_download(command):
    notification = EmployeeRecordUpdateNotificationFactory(ready_for_transfer=True)

    command.handle(upload=True, download=True, preflight=False, wet_run=False)
    notification.refresh_from_db()
    assert notification.status == Status.NEW


@freezegun.freeze_time("2021-09-27")
def test_upload_and_download(snapshot, sftp_directory, command):
    notification = EmployeeRecordUpdateNotificationFactory(ready_for_transfer=True)

    command.handle(upload=True, download=False, preflight=False, wet_run=True)
    notification.refresh_from_db()
    assert notification.status == Status.SENT
    assert notification.asp_batch_line_number == 1
    assert notification.asp_batch_file is not None

    process_incoming_file(sftp_directory, "0000", "OK")

    command.handle(upload=False, download=True, preflight=False, wet_run=True)
    notification.refresh_from_db()
    assert notification.status == Status.PROCESSED
    assert notification.asp_processing_code == "0000"
    assert notification.archived_json.get("libelleTraitement") == "OK"

    assert command.stdout.getvalue() == snapshot()
