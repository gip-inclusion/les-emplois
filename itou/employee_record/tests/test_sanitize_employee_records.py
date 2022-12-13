import io

import pytest

from .. import factories, models
from ..management.commands import sanitize_employee_records


@pytest.fixture(name="command")
def command_fixture():
    return sanitize_employee_records.Command(stdout=io.StringIO(), stderr=io.StringIO())


def test_handle_dry_run_option(mocker, command):
    mocker.patch.object(command, "_check_approvals")
    mocker.patch.object(command, "_check_jobseeker_profiles")
    mocker.patch.object(command, "_check_3436_error_code")
    mocker.patch.object(command, "_check_orphans")

    command.handle(dry_run=True)
    assert command.stdout.getvalue().split("\n") == [
        "+ Checking employee records coherence before transfering to ASP",
        " - DRY-RUN mode: not fixing, just reporting",
        "+ Employee records sanitizing done. Have a great day!",
        "",
    ]


def test_3436_errors_check(command):
    # Check for 3436 errors fix (ASP duplicates)

    employee_record = factories.EmployeeRecordWithProfileFactory(
        status=models.Status.REJECTED,
        asp_processing_code=models.EmployeeRecord.ASP_DUPLICATE_ERROR_CODE,
    )

    command._check_3436_error_code(dry_run=False)

    # Exterminate 3436s
    employee_record.refresh_from_db()
    assert employee_record.status == models.Status.PROCESSED
    assert employee_record.processed_as_duplicate is True
    assert command.stdout.getvalue().split("\n") == [
        "* Checking REJECTED employee records with error 3436 (duplicates):",
        " - found 1 error(s)",
        " - fixing 3436 errors: forcing status to PROCESSED",
        " - done!",
        "",
    ]


def test_orphans_check(command):
    # Check if any orphan (mismatch in `asp_id`)

    employee_record = factories.BareEmployeeRecordFactory(status=models.Status.PROCESSED)
    employee_record.asp_id += 1
    employee_record.save()

    command._check_orphans(dry_run=False)

    employee_record.refresh_from_db()
    assert employee_record.status == models.Status.DISABLED
    assert command.stdout.getvalue().split("\n") == [
        "* Checking PROCESSED employee records with bad asp_id (orphans):",
        " - found 1 orphan(s)",
        " - fixing orphans: switching status to DISABLED",
        " - done!",
        "",
    ]


def test_profile_errors_check(command):
    # Check for profile errors during sanitize_employee_records

    # This factory does not define a profile
    employee_record = factories.EmployeeRecordFactory()

    command._check_jobseeker_profiles(dry_run=False)

    employee_record.refresh_from_db()
    assert employee_record.status == models.Status.DISABLED
    assert command.stdout.getvalue().split("\n") == [
        "* Checking employee records job seeker profile:",
        " - found 1 job seeker profile(s) without HEXA address",
        " - fixing missing address in profiles: switching status to DISABLED",
        " - done!",
        " - found 1 empty job seeker profile(s)",
        " - fixing missing jobseeker profiles: switching status to DISABLED",
        " - done!",
        "",
    ]


def test_missing_approvals(command):
    # Check for employee record without approval (through job application)

    employee_record = factories.EmployeeRecordFactory()
    employee_record.job_application.approval = None
    employee_record.job_application.save()

    command._check_approvals(dry_run=False)

    assert models.EmployeeRecord.objects.count() == 0
    assert command.stdout.getvalue().split("\n") == [
        "* Checking missing employee records approval:",
        " - found 1 missing approval(s)",
        " - fixing missing approvals: DELETING employee records",
        " - done!",
        "",
    ]
