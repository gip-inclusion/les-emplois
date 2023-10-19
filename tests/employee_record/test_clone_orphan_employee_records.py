import io

import pytest
from django.core.management import call_command

from itou.companies import enums as companies_enums, models as siaes_models
from itou.employee_record.management.commands import clone_orphan_employee_records
from tests.employee_record import factories


@pytest.fixture(name="command")
def command_fixture():
    return clone_orphan_employee_records.Command(stdout=io.StringIO(), stderr=io.StringIO())


def test_management_command_default_run(command):
    employee_record = factories.EmployeeRecordFactory(orphan=True)
    siae = employee_record.job_application.to_siae

    command.handle(for_siae=siae.pk)

    assert command.stderr.getvalue().split("\n") == [
        f"Clone orphans employee records of {siae=} {siae.siret=} {siae.convention.asp_id=}",
        "1/1 orphans employee records will be cloned",
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
    siae = employee_record.job_application.to_siae
    # Create non-orphan employee records with the old and new ASP ID to check filtering
    factories.EmployeeRecordFactory(job_application__to_siae__convention__asp_id=employee_record.asp_id)
    factories.EmployeeRecordFactory(job_application__to_siae__convention__asp_id=siae.convention.asp_id)

    command.handle(for_siae=siae.pk, wet_run=True)

    assert command.stderr.getvalue().split("\n") == [
        f"Clone orphans employee records of {siae=} {siae.siret=} {siae.convention.asp_id=}",
        "1/1 orphans employee records will be cloned",
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
        job_application__to_siae__kind=companies_enums.CompanyKind.EI,
    )
    siae = employee_record.job_application.to_siae

    # Create a non-orphan employee record that use the same convention
    factories.EmployeeRecordFactory(
        job_application__to_siae__kind=companies_enums.CompanyKind.ACI,
        job_application__to_siae__convention__asp_id=siae.convention.asp_id,
    )
    # SiaeConventionFactory() use the `django_get_or_create` option to match the ("asp_id", "kind")` unique
    # constraint, and in this test case we need to be sure that more than one convention share the same asp_id.
    assert siaes_models.SiaeConvention.objects.filter(asp_id=siae.convention.asp_id).count() == 2

    command.handle(for_siae=siae.pk)

    assert command.stderr.getvalue().split("\n") == [
        f"Clone orphans employee records of {siae=} {siae.siret=} {siae.convention.asp_id=}",
        "1/1 orphans employee records will be cloned",
        "Option --wet-run was not used so nothing will be cloned.",
        "Done!",
        "",
    ]
    assert command.stdout.getvalue().split("\n") == [
        f"Cloning employee_record.pk={employee_record.pk}...",
        "",
    ]


def test_management_command_do_not_try_to_create_multiple_records_for_the_same_approval(command):
    first_employee_record = factories.EmployeeRecordFactory(
        orphan=True,
        job_application__to_siae__kind=companies_enums.CompanyKind.EI,
    )
    second_employee_record = first_employee_record.clone()  # Use clone to create the most perfect duplicate
    siae = second_employee_record.job_application.to_siae

    command.handle(for_siae=siae.pk)

    assert command.stderr.getvalue().split("\n") == [
        f"Clone orphans employee records of {siae=} {siae.siret=} {siae.convention.asp_id=}",
        "0/1 orphans employee records will be cloned",
        "Option --wet-run was not used so nothing will be cloned.",
        "Done!",
        "",
    ]
    assert command.stdout.getvalue().split("\n") == [""]


def test_management_command_name(faker):
    call_command("clone_orphan_employee_records", "--for-siae", faker.pyint())
