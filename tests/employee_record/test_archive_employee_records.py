import io

import pytest
from django.core.management import call_command

from itou.employee_record.enums import Status
from itou.employee_record.management.commands import archive_employee_records
from itou.employee_record.models import EmployeeRecord
from tests.employee_record import factories


@pytest.fixture(name="command")
def command_fixture():
    return archive_employee_records.Command(stdout=io.StringIO(), stderr=io.StringIO())


def test_management_command_default_run(command, snapshot):
    employee_record = factories.EmployeeRecordFactory(pk=42, archivable=True)
    assert list(EmployeeRecord.objects.archivable()) == [employee_record]

    command.handle(wet_run=False)
    employee_record.refresh_from_db()

    assert employee_record.status != Status.ARCHIVED
    assert command.stdout.getvalue() == snapshot


def test_management_command_wet_run(command, snapshot):
    employee_record = factories.EmployeeRecordFactory(pk=42, archivable=True)

    command.handle(wet_run=True)
    employee_record.refresh_from_db()

    assert employee_record.status == Status.ARCHIVED
    assert employee_record.archived_json is None
    assert command.stdout.getvalue() == snapshot


def test_management_command_name():
    call_command("archive_employee_records")
