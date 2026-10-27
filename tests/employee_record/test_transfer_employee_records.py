import json
import re
import uuid

import freezegun
import pytest
from django.conf import settings
from django.core.management import call_command
from django.test.utils import override_settings
from django.utils import timezone
from itoutils.django.testing import assertSnapshotQueries

from itou.employee_record.enums import NotificationStatus, Status
from itou.employee_record.models import EmployeeRecordBatch
from itou.job_applications.enums import JobApplicationState
from itou.utils import triggers
from itou.utils.admin import get_admin_url
from itou.utils.asp import REMOTE_DOWNLOAD_DIR, REMOTE_UPLOAD_DIR
from tests.approvals.factories import ProlongationFactory, SuspensionFactory
from tests.employee_record.factories import EmployeeRecordFactory, EmployeeRecordUpdateNotificationFactory
from tests.users.factories import JobSeekerProfileFactory


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
        "Management command itou.employee_record.management.commands.transfer_employee_records succeeded in "
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
    call_command("transfer_employee_records", upload=False, download=True, preflight=False, wet_run=False)
    assert process_output(caplog.messages) == snapshot


@pytest.mark.usefixtures("mocked_sftp")
def test_option_asp_test(snapshot, caplog):
    call_command(
        "transfer_employee_records", asp_test=True, upload=False, download=True, preflight=False, wet_run=False
    )
    assert process_output(caplog.messages) == snapshot


@pytest.mark.usefixtures("mocked_sftp")
def test_connection_error(mocker, caplog):
    mocker.patch("itou.utils.asp.get_sftp_connection", side_effect=Exception)
    employee_record = EmployeeRecordFactory(ready_for_transfer=True)

    with pytest.raises(Exception):
        call_command("transfer_employee_records", upload=True, download=False, preflight=False, wet_run=True)

    employee_record.refresh_from_db()
    assert employee_record.status == Status.READY
    assert caplog.messages[-1].startswith(
        "Management command itou.employee_record.management.commands.transfer_employee_records failed in "
    )
    assert caplog.messages[:-1] == [
        "Error when executing itou.employee_record.management.commands.transfer_employee_records"
    ]


@pytest.mark.usefixtures("mocked_sftp")
def test_preflight(snapshot, caplog):
    EmployeeRecordFactory.create_batch(3, ready_for_transfer=True)

    call_command("transfer_employee_records", preflight=True, upload=False, download=False, wet_run=False)
    assert process_output(caplog.messages) == snapshot


@pytest.mark.usefixtures("mocked_sftp")
def test_preflight_without_object(snapshot, caplog):
    call_command("transfer_employee_records", preflight=True, upload=False, download=False, wet_run=False)
    assert process_output(caplog.messages) == snapshot


@pytest.mark.usefixtures("mocked_sftp")
def test_preflight_with_error(snapshot, caplog):
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

    call_command("transfer_employee_records", preflight=True, upload=False, download=False, wet_run=False)
    assert process_output(caplog.messages) == snapshot


@pytest.mark.usefixtures("mocked_sftp")
def test_preflight_without_an_accepted_job_application(caplog, snapshot):
    employee_record = EmployeeRecordFactory(ready_for_transfer=True)
    job_application = employee_record.job_application
    # we manually "corrupt" the job application to test the preflight's ability to detect it as an error
    job_application.state = JobApplicationState.NEW
    job_application.approval = None
    job_application.eligibility_diagnosis = None
    job_application.processed_at = None
    job_application.save(update_fields=("state", "approval", "eligibility_diagnosis", "processed_at", "updated_at"))

    call_command("transfer_employee_records", preflight=True, upload=False, download=False, wet_run=False)
    assert process_output(caplog.messages) == snapshot


@freezegun.freeze_time("2021-09-27")
@pytest.mark.usefixtures("mocked_sftp")
def test_upload_file_error(snapshot, sftp_directory, caplog):
    employee_record = EmployeeRecordFactory(ready_for_transfer=True)
    sftp_directory.joinpath(REMOTE_UPLOAD_DIR).rmdir()

    call_command("transfer_employee_records", upload=True, download=False, preflight=False, wet_run=True)

    employee_record.refresh_from_db()
    assert employee_record.status == Status.READY
    assert process_output(caplog.messages) == snapshot


@freezegun.freeze_time("2021-09-27")
@pytest.mark.usefixtures("mocked_sftp")
def test_upload_only_create_a_limited_number_of_files(mocker, snapshot, sftp_directory, caplog):
    mocker.patch.object(EmployeeRecordBatch, "MAX_EMPLOYEE_RECORDS", 1)
    EmployeeRecordFactory(pk=4321, ready_for_transfer=True)
    EmployeeRecordFactory(pk=1234, ready_for_transfer=True)

    call_command("transfer_employee_records", upload=True, download=False, preflight=False, wet_run=True)
    assert len(list(sftp_directory.joinpath(REMOTE_UPLOAD_DIR).iterdir())) == 1

    assert (
        process_output(
            [re.sub(r"<EmployeeRecord: PK:1234 .+?>", "<EmployeeRecord pk=1234>", msg) for msg in caplog.messages]
        )
        == snapshot()
    )


@freezegun.freeze_time("2021-09-27")
@pytest.mark.usefixtures("mocked_sftp")
def test_upload_only_send_a_limited_number_of_rows(mocker, sftp_directory):
    mocker.patch.object(EmployeeRecordBatch, "MAX_EMPLOYEE_RECORDS", 1)
    EmployeeRecordFactory.create_batch(2, ready_for_transfer=True)

    call_command("transfer_employee_records", upload=True, download=False, preflight=False, wet_run=True)
    for file in sftp_directory.joinpath(REMOTE_UPLOAD_DIR).iterdir():
        assert len(file.read_text().splitlines()) == 1


@pytest.mark.usefixtures("mocked_sftp")
def test_upload_without_an_accepted_job_application(caplog, snapshot):
    employee_record = EmployeeRecordFactory(ready_for_transfer=True)
    job_application = employee_record.job_application
    # we manually "corrupt" the job application to test the command's ability to detect it as an error
    job_application.state = JobApplicationState.CANCELLED
    job_application.approval = None
    job_application.eligibility_diagnosis = None
    job_application.save(update_fields=("state", "approval", "eligibility_diagnosis", "updated_at"))

    call_command("transfer_employee_records", preflight=False, upload=True, download=False, wet_run=False)
    assert process_output(caplog.messages) == snapshot


@pytest.mark.usefixtures("mocked_sftp")
def test_download_file_error(snapshot, sftp_directory, caplog):
    sftp_directory.joinpath("retrait/RIAE_FS_00000000000000_FichierRetour.json").touch(0o000)

    call_command("transfer_employee_records", upload=False, download=True, preflight=False, wet_run=True)
    assert process_output(caplog.messages) == snapshot


@freezegun.freeze_time("2021-09-27")
@pytest.mark.usefixtures("mocked_sftp")
def test_dry_run_upload_and_download():
    employee_record = EmployeeRecordFactory(ready_for_transfer=True)

    call_command("transfer_employee_records", upload=True, download=True, preflight=False, wet_run=False)
    employee_record.refresh_from_db()
    assert employee_record.status == Status.READY


@freezegun.freeze_time("2021-09-27")
@pytest.mark.usefixtures("mocked_sftp")
def test_upload_and_download(snapshot, sftp_directory, caplog):
    employee_record = EmployeeRecordFactory(ready_for_transfer=True)

    with assertSnapshotQueries(snapshot(name="upload")):
        call_command("transfer_employee_records", upload=True, download=False, preflight=False, wet_run=True)
    employee_record.refresh_from_db()
    assert employee_record.status == Status.SENT
    assert employee_record.asp_batch_line_number == 1
    assert employee_record.asp_batch_file is not None

    process_incoming_file(sftp_directory, "0000", "OK")

    with assertSnapshotQueries(snapshot(name="download")):
        call_command("transfer_employee_records", upload=False, download=True, preflight=False, wet_run=True)
    employee_record.refresh_from_db()
    assert employee_record.status == Status.PROCESSED
    assert employee_record.asp_processing_code == "0000"
    assert employee_record.archived_json.get("libelleTraitement") == "OK"

    assert process_output(caplog.messages) == snapshot(name="logs")


@pytest.mark.usefixtures("mocked_sftp")
def test_duplicates_automatic_processing(sftp_directory):
    employee_record = EmployeeRecordFactory(ready_for_transfer=True)

    call_command("transfer_employee_records", upload=True, download=False, preflight=False, wet_run=True)
    process_incoming_file(sftp_directory, "3436", "Duplicate")

    call_command("transfer_employee_records", upload=False, download=True, preflight=False, wet_run=True)
    employee_record.refresh_from_db()
    assert employee_record.status == Status.PROCESSED
    assert employee_record.asp_processing_code == "3436"
    assert employee_record.archived_json.get("libelleTraitement") == "Duplicate"
    assert employee_record.processed_as_duplicate is True


@pytest.mark.usefixtures("mocked_sftp")
def test_3437_automatic_processing(sftp_directory):
    employee_record = EmployeeRecordFactory(ready_for_transfer=True)
    new_asp_uid = "1234567890abcdef1234567890abcd"

    call_command("transfer_employee_records", upload=True, download=False, preflight=False, wet_run=True)
    processing_label = (
        "Un salarié existe déjà pour cette structure avec un identifiant Plate-forme de l'inclusion "
        f"différent. ({new_asp_uid})"
    )
    process_incoming_file(sftp_directory, "3437", processing_label)

    with triggers.fake_context():  # Needed because the test wasn't using call_command and would fail without it
        call_command("transfer_employee_records", upload=False, download=True, preflight=False, wet_run=True)
    employee_record.refresh_from_db()
    assert employee_record.status == Status.READY
    assert employee_record.asp_processing_code == "3437"
    assert employee_record.archived_json.get("libelleTraitement") == processing_label
    assert employee_record.job_application.job_seeker.jobseeker_profile.asp_uid == new_asp_uid


@pytest.mark.usefixtures("mocked_sftp")
def test_3437_processing_with_duplicate(sftp_directory, mailoutbox, django_capture_on_commit_callbacks):
    employee_record = EmployeeRecordFactory(ready_for_transfer=True)
    duplicate_profile = JobSeekerProfileFactory()
    new_asp_uid = duplicate_profile.asp_uid

    call_command("transfer_employee_records", upload=True, download=False, preflight=False, wet_run=True)
    processing_label = (
        "Un salarié existe déjà pour cette structure avec un identifiant Plate-forme de l'inclusion "
        f"différent. ({new_asp_uid})"
    )
    process_incoming_file(sftp_directory, "3437", processing_label)

    with django_capture_on_commit_callbacks(execute=True):
        call_command("transfer_employee_records", upload=False, download=True, preflight=False, wet_run=True)
    employee_record.refresh_from_db()
    assert employee_record.status == Status.REJECTED
    assert employee_record.asp_processing_code == "3437"
    assert employee_record.archived_json.get("libelleTraitement") == processing_label
    assert employee_record.job_application.job_seeker.jobseeker_profile.asp_uid != new_asp_uid
    [support_email] = mailoutbox
    assert support_email.to == [settings.ITOU_EMAIL_CONTACT]
    assert "Doublon de compte à régulariser suite à une erreur 3437" in support_email.subject
    assert get_admin_url(employee_record) in support_email.body
    assert get_admin_url(employee_record.job_application.job_seeker) in support_email.body
    assert get_admin_url(duplicate_profile.user) in support_email.body


@pytest.mark.parametrize("extension_class", [ProlongationFactory, SuspensionFactory])
@pytest.mark.usefixtures("mocked_sftp")
def test_duplicates_with_an_extension_generate_an_update_notification(sftp_directory, extension_class):
    employee_record = EmployeeRecordFactory(ready_for_transfer=True)
    extension_class(approval=employee_record.job_application.approval)

    call_command("transfer_employee_records", upload=True, download=False, preflight=False, wet_run=True)
    process_incoming_file(sftp_directory, "3436", "Duplicate")

    call_command("transfer_employee_records", upload=False, download=True, preflight=False, wet_run=True)
    assert employee_record.update_notifications.count() == 1
    assert employee_record.update_notifications.get().status == NotificationStatus.NEW


@pytest.mark.parametrize("status", set(NotificationStatus) - {NotificationStatus.NEW})
@pytest.mark.parametrize("extension_class", [ProlongationFactory, SuspensionFactory])
@pytest.mark.usefixtures("mocked_sftp")
def test_duplicates_with_an_extension_generate_a_pristine_update_notification(sftp_directory, status, extension_class):
    employee_record = EmployeeRecordFactory(ready_for_transfer=True)
    EmployeeRecordUpdateNotificationFactory(employee_record=employee_record, status=status)
    extension_class(approval=employee_record.job_application.approval)

    call_command("transfer_employee_records", upload=True, download=False, preflight=False, wet_run=True)
    process_incoming_file(sftp_directory, "3436", "Duplicate")

    call_command("transfer_employee_records", upload=False, download=True, preflight=False, wet_run=True)
    assert employee_record.update_notifications.count() == 2
    assert employee_record.update_notifications.latest("created_at").status == NotificationStatus.NEW


@pytest.mark.parametrize("extension_class", [ProlongationFactory, SuspensionFactory])
@pytest.mark.usefixtures("mocked_sftp")
def test_duplicates_with_an_extension_update_the_existing_new_notification(sftp_directory, extension_class):
    employee_record = EmployeeRecordFactory(ready_for_transfer=True)
    EmployeeRecordUpdateNotificationFactory(employee_record=employee_record, status=NotificationStatus.NEW)
    extension_class(approval=employee_record.job_application.approval)

    call_command("transfer_employee_records", upload=True, download=False, preflight=False, wet_run=True)
    process_incoming_file(sftp_directory, "3436", "Duplicate")

    with freezegun.freeze_time():
        expected_updated_at = timezone.now()
        call_command("transfer_employee_records", upload=False, download=True, preflight=False, wet_run=True)
    assert employee_record.update_notifications.count() == 1
    notification = employee_record.update_notifications.get()
    assert notification.status == NotificationStatus.NEW
    assert notification.updated_at == expected_updated_at
