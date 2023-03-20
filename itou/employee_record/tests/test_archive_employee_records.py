import io

import pytest
from django.core.management import call_command

from .. import factories
from ..enums import Status
from ..management.commands import archive_employee_records
from ..models import EmployeeRecord


@pytest.fixture(name="command")
def command_fixture():
    return archive_employee_records.Command(stdout=io.StringIO(), stderr=io.StringIO())


def test_management_command_default_run(command):
    employee_record = factories.BareEmployeeRecordFactory(archivable=True)
    assert list(EmployeeRecord.objects.archivable()) == [employee_record]

    command.handle()
    employee_record.refresh_from_db()

    assert employee_record.status != Status.ARCHIVED
    assert command.stdout.getvalue().split("\n") == [
        "Archiving employee records (more than 390 days old)",
        "Found 1 archivable employee record(s)",
        "",
    ]


def test_management_command_wet_run(command):
    employee_record = factories.BareEmployeeRecordFactory(archivable=True)

    command.handle(wet_run=True)
    employee_record.refresh_from_db()

    assert employee_record.status == Status.ARCHIVED
    assert employee_record.archived_json is None
    assert command.stdout.getvalue().split("\n") == [
        "Archiving employee records (more than 390 days old)",
        "Found 1 archivable employee record(s)",
        "Archived 1/1 employee record(s)",
        "",
    ]


def test_management_command_name(faker):
    call_command("archive_employee_records")
