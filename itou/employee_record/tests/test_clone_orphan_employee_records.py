import io

import pytest
from django.core.management import call_command

from .. import factories
from ..management.commands import clone_orphan_employee_records


@pytest.fixture(name="command")
def command_fixture():
    return clone_orphan_employee_records.Command(stdout=io.StringIO(), stderr=io.StringIO())


def test_management_command_default_run(command):
    employee_record = factories.EmployeeRecordFactory(orphan=True)
    old_asp_id, new_asp_id = employee_record.asp_id, employee_record.job_application.to_siae.convention.asp_id

    command.handle(
        old_asp_id=old_asp_id,
        new_asp_id=new_asp_id,
    )

    assert command.stderr.getvalue().split("\n") == [
        f"Clone orphans employee records from old_asp_id={old_asp_id} to new_asp_id={new_asp_id}",
        "1 employee records will be cloned",
        "Option --wet-run was not used so nothing will be cloned.",
        "Done!",
        "",
    ]
    assert command.stdout.getvalue().split("\n") == [
        f"Cloning employee_record.pk={employee_record.pk}...",
        "",
    ]


def test_management_command_wet_run(command):
    employee_record = factories.EmployeeRecordFactory(orphan=True)
    old_asp_id, new_asp_id = employee_record.asp_id, employee_record.job_application.to_siae.convention.asp_id
    # Create non-orphan employee records with the old and new ASP ID to check filtering
    factories.EmployeeRecordFactory(job_application__to_siae__convention__asp_id=old_asp_id)
    factories.EmployeeRecordFactory(job_application__to_siae__convention__asp_id=new_asp_id)

    command.handle(
        old_asp_id=old_asp_id,
        new_asp_id=new_asp_id,
        wet_run=True,
    )

    assert command.stderr.getvalue().split("\n") == [
        f"Clone orphans employee records from old_asp_id={old_asp_id} to new_asp_id={new_asp_id}",
        "1 employee records will be cloned",
        "Done!",
        "",
    ]
    assert command.stdout.getvalue().split("\n") == [
        f"Cloning employee_record.pk={employee_record.pk}...",
        f"  Cloning was successful, employee_record_clone.pk={employee_record.pk + 3}",
        "",
    ]


def test_management_command_name(faker):
    call_command("clone_orphan_employee_records", "--old-asp-id", faker.pyint(), "--new-asp-id", faker.pyint())
