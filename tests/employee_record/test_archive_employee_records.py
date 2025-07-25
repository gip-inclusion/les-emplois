import re

import pytest
from django.core.management import call_command

from itou.employee_record.enums import Status
from itou.employee_record.management.commands import archive_employee_records
from itou.employee_record.models import EmployeeRecord
from tests.employee_record import factories


@pytest.fixture(name="command")
def command_fixture():
    return archive_employee_records.Command()


def test_management_command_default_run(command, snapshot, caplog):
    employee_record = factories.EmployeeRecordFactory(pk=42, archivable=True, archived_json="")
    assert list(EmployeeRecord.objects.archivable()) == [employee_record]

    command.handle(wet_run=False)
    employee_record.refresh_from_db()

    assert employee_record.status != Status.ARCHIVED
    assert employee_record.archived_json is not None
    assert [re.sub(r"<EmployeeRecord: .+?>", "[EMPLOYEE RECORD]", msg) for msg in caplog.messages] == snapshot()


def test_management_command_wet_run(command, snapshot, caplog):
    employee_record = factories.EmployeeRecordFactory(pk=42, archivable=True, archived_json="")

    command.handle(wet_run=True)
    employee_record.refresh_from_db()

    assert employee_record.status == Status.ARCHIVED
    assert employee_record.archived_json is None
    assert [re.sub(r"<EmployeeRecord: .+?>", "[EMPLOYEE RECORD]", msg) for msg in caplog.messages] == snapshot()


def test_management_command_name():
    call_command("archive_employee_records")
