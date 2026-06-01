import re

from django.core.management import call_command

from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord
from tests.employee_record import factories


def process_output(caplog_messages):
    assert caplog_messages[-1].startswith(
        "Management command itou.employee_record.management.commands.archive_employee_records succeeded in "
    )
    return [re.sub(r"<EmployeeRecord: .+?>", "[EMPLOYEE RECORD]", msg) for msg in caplog_messages[:-1]]


def test_management_command_default_run(snapshot, caplog):
    employee_record = factories.EmployeeRecordFactory(pk=42, archivable=True, archived_json="")
    assert list(EmployeeRecord.objects.archivable()) == [employee_record]

    call_command("archive_employee_records", wet_run=False)
    employee_record.refresh_from_db()

    assert employee_record.status != Status.ARCHIVED
    assert employee_record.archived_json is not None
    assert process_output(caplog.messages) == snapshot()


def test_management_command_wet_run(snapshot, caplog):
    employee_record = factories.EmployeeRecordFactory(pk=42, archivable=True, archived_json="")

    call_command("archive_employee_records", wet_run=True)
    employee_record.refresh_from_db()

    assert employee_record.status == Status.ARCHIVED
    assert employee_record.archived_json is None
    assert process_output(caplog.messages) == snapshot()
