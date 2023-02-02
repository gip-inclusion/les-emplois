import io

import pytest
from django.core.management import call_command

from itou.siaes import enums as siaes_enums, models as siaes_models

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


def test_management_command_when_the_new_asp_id_is_used_by_multiple_convention(command):
    employee_record = factories.EmployeeRecordFactory(
        orphan=True,
        job_application__to_siae__kind=siaes_enums.SiaeKind.EI,
    )
    old_asp_id, new_asp_id = employee_record.asp_id, employee_record.job_application.to_siae.convention.asp_id
    factories.EmployeeRecordFactory(
        job_application__to_siae__kind=siaes_enums.SiaeKind.ACI,
        job_application__to_siae__convention__asp_id=new_asp_id,
    )

    # SiaeConventionFactory() use the `django_get_or_create` option to match the ("asp_id", "kind")` unique
    # constraint, and in this test case we need to be sure that more than one convention share the same asp_id.
    assert siaes_models.SiaeConvention.objects.filter(asp_id=new_asp_id).count() == 2

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


def test_management_command_name(faker):
    call_command("clone_orphan_employee_records", "--old-asp-id", faker.pyint(), "--new-asp-id", faker.pyint())
