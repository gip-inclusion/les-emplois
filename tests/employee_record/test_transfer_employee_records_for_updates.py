import json
import re
import uuid

import freezegun
import pytest
from django.core.management import call_command
from django.test.utils import override_settings
from django.utils import timezone
from itoutils.django.testing import assertSnapshotQueries

from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecordBatch
from itou.utils.asp import REMOTE_DOWNLOAD_DIR, REMOTE_UPLOAD_DIR
from tests.employee_record.factories import EmployeeRecordFactory


@pytest.fixture(name="mocked_sftp")
def mocked_sftp_fixture(mocker, settings, sftp_directory, sftp_client_factory):
    # Set required settings
    settings.ASP_SFTP_HOST = "0.0.0.0"  # non-routable IP, just in case :)
    settings.ASP_SFTP_USER = "django_tests"

    # Setup directory
    sftp_directory.joinpath(REMOTE_UPLOAD_DIR).mkdir()
    sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR).mkdir()

    # Mock the SFTP connection
    mocker.patch("itou.utils.asp.get_sftp_connection", sftp_client_factory)


def process_output(caplog_messages):
    assert caplog_messages[-1].startswith(
        "Management command itou.employee_record.management.commands.transfer_employee_records_for_updates succeeded "
    )
    return [re.sub(r"<EmployeeRecord: .+?>", "[EMPLOYEE RECORD]", msg) for msg in caplog_messages[:-1]]


def process_incoming_file(sftp_directory, code, message):
    for file in sftp_directory.joinpath(REMOTE_UPLOAD_DIR).iterdir():
        batch = json.loads(file.read_text())

        for employee_record in batch.get("lignesTelechargement", []):
            employee_record["codeTraitement"] = code
            employee_record["libelleTraitement"] = message

        feedback_file = sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR, EmployeeRecordBatch.feedback_filename(file.name))
        feedback_file.write_text(json.dumps(batch))


@override_settings(ASP_SFTP_HOST="")
@pytest.mark.usefixtures("mocked_sftp")
def test_missing_environment_asp_sftp_host(snapshot, caplog):
    call_command("transfer_employee_records_for_updates", upload=False, download=True, preflight=False, wet_run=False)
    assert process_output(caplog.messages) == snapshot


@pytest.mark.usefixtures("mocked_sftp")
def test_option_asp_test(snapshot, caplog):
    call_command(
        "transfer_employee_records_for_updates",
        asp_test=True,
        upload=False,
        download=True,
        preflight=False,
        wet_run=False,
    )
    assert process_output(caplog.messages) == snapshot


@pytest.mark.usefixtures("mocked_sftp")
def test_connection_error(mocker, caplog):
    mocker.patch("itou.utils.asp.get_sftp_connection", side_effect=Exception)
    employee_record = EmployeeRecordFactory(ready_for_transfer=True, status=Status.MODIFICATION_PENDING)

    with pytest.raises(Exception):
        call_command(
            "transfer_employee_records_for_updates", upload=True, download=False, preflight=False, wet_run=True
        )

    employee_record.refresh_from_db()
    assert employee_record.status == Status.MODIFICATION_PENDING
    assert caplog.messages[-1].startswith(
        "Management command itou.employee_record.management.commands.transfer_employee_records_for_updates failed in "
    )
    assert caplog.messages[:-1] == [
        "Error when executing itou.employee_record.management.commands.transfer_employee_records_for_updates"
    ]


@pytest.mark.usefixtures("mocked_sftp")
def test_preflight(snapshot, caplog):
    EmployeeRecordFactory.create_batch(3, ready_for_transfer=True, status=Status.MODIFICATION_PENDING)

    call_command("transfer_employee_records_for_updates", preflight=True, upload=False, download=False, wet_run=False)
    assert process_output(caplog.messages) == snapshot


@pytest.mark.usefixtures("mocked_sftp")
def test_preflight_without_object(snapshot, caplog):
    call_command("transfer_employee_records_for_updates", preflight=True, upload=False, download=False, wet_run=False)
    assert process_output(caplog.messages) == snapshot


@pytest.mark.usefixtures("mocked_sftp")
def test_preflight_with_error(snapshot, caplog):
    EmployeeRecordFactory(
        status=Status.MODIFICATION_PENDING,
        approval_number="",
        job_application__approval=None,
        # Make sure a missing NTT does not change the error message
        job_application__job_seeker__jobseeker_profile__with_classic_nir=True,
        # Data used by the snapshot
        pk=42,
        job_application__pk=uuid.UUID("49536a29-88b5-49c3-8c46-333bbbc36308"),
        job_application__to_company__siret="17483349486512",
        job_application__to_company__convention__asp_id="21",
        job_application__approval__number="XXXXX3724456",
        job_application__job_seeker__pk=4242,
    )

    call_command("transfer_employee_records_for_updates", preflight=True, upload=False, download=False, wet_run=False)
    assert process_output(caplog.messages) == snapshot


@freezegun.freeze_time("2021-09-27")
@pytest.mark.usefixtures("mocked_sftp")
def test_upload_file_error(faker, snapshot, sftp_directory, caplog):
    employee_record = EmployeeRecordFactory(ready_for_transfer=True, status=Status.MODIFICATION_PENDING)
    sftp_directory.joinpath(REMOTE_UPLOAD_DIR).rmdir()

    call_command("transfer_employee_records_for_updates", upload=True, download=False, preflight=False, wet_run=True)

    employee_record.refresh_from_db()
    assert employee_record.status == Status.MODIFICATION_PENDING
    assert process_output(caplog.messages) == snapshot


@freezegun.freeze_time("2021-09-27")
@pytest.mark.usefixtures("mocked_sftp")
def test_upload_only_create_a_limited_number_of_files(mocker, snapshot, sftp_directory, caplog):
    mocker.patch.object(EmployeeRecordBatch, "MAX_EMPLOYEE_RECORDS", 1)
    EmployeeRecordFactory(pk=4321, ready_for_transfer=True, status=Status.MODIFICATION_PENDING)
    EmployeeRecordFactory(pk=1234, ready_for_transfer=True, status=Status.MODIFICATION_PENDING)

    call_command("transfer_employee_records_for_updates", upload=True, download=False, preflight=False, wet_run=True)
    assert len(list(sftp_directory.joinpath(REMOTE_UPLOAD_DIR).iterdir())) == 1

    assert process_output(caplog.messages) == snapshot


@freezegun.freeze_time("2021-09-27")
@pytest.mark.usefixtures("mocked_sftp")
def test_upload_only_send_a_limited_number_of_rows(mocker, sftp_directory):
    mocker.patch.object(EmployeeRecordBatch, "MAX_EMPLOYEE_RECORDS", 1)
    EmployeeRecordFactory.create_batch(2, ready_for_transfer=True, status=Status.MODIFICATION_PENDING)

    call_command("transfer_employee_records_for_updates", upload=True, download=False, preflight=False, wet_run=True)
    for file in sftp_directory.joinpath(REMOTE_UPLOAD_DIR).iterdir():
        assert len(file.read_text().splitlines()) == 1


@pytest.mark.usefixtures("mocked_sftp")
def test_download_file_error(faker, snapshot, sftp_directory, caplog):
    sftp_directory.joinpath("retrait/RIAE_FS_00000000000000_FichierRetour.json").touch(0o000)

    call_command("transfer_employee_records_for_updates", upload=False, download=True, preflight=False, wet_run=True)
    assert process_output(caplog.messages) == snapshot


@freezegun.freeze_time("2021-09-27")
@pytest.mark.usefixtures("mocked_sftp")
def test_dry_run_upload_and_download():
    processed_employee_record = EmployeeRecordFactory(
        ready_for_transfer=True, status=Status.PROCESSED, watched_data_updated_at=timezone.now()
    )
    update_pending_employee_record = EmployeeRecordFactory(ready_for_transfer=True, status=Status.MODIFICATION_PENDING)

    call_command("transfer_employee_records_for_updates", upload=True, download=True, preflight=False, wet_run=False)
    processed_employee_record.refresh_from_db()
    assert processed_employee_record.status == Status.PROCESSED
    update_pending_employee_record.refresh_from_db()
    assert update_pending_employee_record.status == Status.MODIFICATION_PENDING


@freezegun.freeze_time("2021-09-27")
@pytest.mark.usefixtures("mocked_sftp")
def test_upload_and_download(snapshot, sftp_directory, caplog):
    processed_employee_record = EmployeeRecordFactory(
        ready_for_transfer=True, status=Status.PROCESSED, watched_data_updated_at=timezone.now()
    )
    update_pending_employee_record = EmployeeRecordFactory(ready_for_transfer=True, status=Status.MODIFICATION_PENDING)

    with assertSnapshotQueries(snapshot(name="upload")):
        call_command(
            "transfer_employee_records_for_updates", upload=True, download=False, preflight=False, wet_run=True
        )
    for idx, employee_record in enumerate([processed_employee_record, update_pending_employee_record], start=1):
        employee_record.refresh_from_db()
        assert employee_record.status == Status.MODIFICATION_SENT
        assert employee_record.asp_batch_line_number == idx
        assert employee_record.asp_batch_file is not None

    process_incoming_file(sftp_directory, "0000", "OK")

    caplog.clear()
    with assertSnapshotQueries(snapshot(name="download")):
        call_command(
            "transfer_employee_records_for_updates", upload=False, download=True, preflight=False, wet_run=True
        )
    for employee_record in [processed_employee_record, update_pending_employee_record]:
        employee_record.refresh_from_db()
        assert employee_record.status == Status.PROCESSED
        assert employee_record.asp_processing_code == "0000"
        assert employee_record.archived_json.get("libelleTraitement") == "OK"

    assert [
        re.sub(r"employee_record=\d+", "employee_record=[EMPLOYEE RECORD PK]", msg)
        for msg in process_output(caplog.messages)
    ] == snapshot(name="logs")


@freezegun.freeze_time("2021-09-27")
@pytest.mark.usefixtures("mocked_sftp")
def test_parse_file(snapshot, sftp_directory, caplog):
    processed_employee_record = EmployeeRecordFactory(
        ready_for_transfer=True, status=Status.PROCESSED, watched_data_updated_at=timezone.now()
    )
    update_pending_employee_record = EmployeeRecordFactory(ready_for_transfer=True, status=Status.MODIFICATION_PENDING)

    call_command("transfer_employee_records_for_updates", upload=True, download=False, preflight=False, wet_run=True)
    for idx, employee_record in enumerate([processed_employee_record, update_pending_employee_record], start=1):
        employee_record.refresh_from_db()
        assert employee_record.status == Status.MODIFICATION_SENT
        assert employee_record.asp_batch_line_number == idx
        assert employee_record.asp_batch_file is not None

    process_incoming_file(sftp_directory, "0000", "OK")
    [feedback_filename] = [
        filepath
        for filepath in sftp_directory.joinpath(REMOTE_DOWNLOAD_DIR).iterdir()
        if filepath.name.endswith("FichierRetour.json")
    ]

    call_command(
        "transfer_employee_records_for_updates",
        parse_file_name=feedback_filename,
        upload=False,
        download=False,
        preflight=False,
        wet_run=True,
    )
    for employee_record in [processed_employee_record, update_pending_employee_record]:
        employee_record.refresh_from_db()
        assert employee_record.status == Status.PROCESSED
        assert employee_record.asp_processing_code == "0000"
        assert employee_record.archived_json.get("libelleTraitement") == "OK"

    assert [
        re.sub(r"employee_record=\d+", "employee_record=[EMPLOYEE RECORD PK]", msg)
        for msg in process_output(caplog.messages)
    ] == snapshot(name="logs")
