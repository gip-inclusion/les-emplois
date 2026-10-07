import time

from django.core.management import call_command

from itou.employee_record.models import (
    EmployeeRecordTransition,
    EmployeeRecordTransitionLog,
)
from tests.employee_record import factories


def process_output(caplog_messages):
    assert caplog_messages[-1].startswith(
        "Management command itou.scripts.management.commands.fix_migrated_employee_record_transition_logs "
        "succeeded in "
    )
    return caplog_messages[:-1]


def test_default_run(caplog):
    factories.EmployeeRecordFactory()  # Ignored record
    employee_record = factories.EmployeeRecordFactory()
    schedule1 = EmployeeRecordTransitionLog.objects.create(
        employee_record=employee_record,
        transition=EmployeeRecordTransition.SCHEDULE_MODIFICATION,
        recovered=True,
    )
    EmployeeRecordTransitionLog.objects.create(
        employee_record=employee_record,
        transition=EmployeeRecordTransition.WAIT_FOR_MODIFICATION_ASP_RESPONSE,
        recovered=True,
    )
    reject = EmployeeRecordTransitionLog.objects.create(
        employee_record=employee_record,
        transition=EmployeeRecordTransition.REJECT_MODIFICATION,
        recovered=True,
        timestamp=schedule1.timestamp,
    )
    # Wait a millisecond to ensure reject and schedule2 aren't too close
    time.sleep(0.001)
    schedule2 = EmployeeRecordTransitionLog.objects.create(
        employee_record=employee_record,
        transition=EmployeeRecordTransition.SCHEDULE_MODIFICATION,
        recovered=True,
    )
    EmployeeRecordTransitionLog.objects.create(
        employee_record=employee_record,
        transition=EmployeeRecordTransition.WAIT_FOR_MODIFICATION_ASP_RESPONSE,
        recovered=True,
    )
    process = EmployeeRecordTransitionLog.objects.create(
        employee_record=employee_record,
        transition=EmployeeRecordTransition.PROCESS_MODIFICATION,
        timestamp=schedule2.timestamp,
        recovered=True,
    )
    assert list(employee_record.logs.order_by("timestamp", "pk").values_list("transition", flat=True)) == [
        EmployeeRecordTransition.SCHEDULE_MODIFICATION,
        EmployeeRecordTransition.REJECT_MODIFICATION,
        EmployeeRecordTransition.WAIT_FOR_MODIFICATION_ASP_RESPONSE,
        EmployeeRecordTransition.SCHEDULE_MODIFICATION,
        EmployeeRecordTransition.PROCESS_MODIFICATION,
        EmployeeRecordTransition.WAIT_FOR_MODIFICATION_ASP_RESPONSE,
    ]

    call_command("fix_migrated_employee_record_transition_logs", wet_run=True)
    assert process_output(caplog.messages) == [
        "Starting fixing transition logs of employee records - starting at pk=0",
        "Checked 1 EmployeeRecord and fixed 2 EmployeeRecordTransitionLog",
        f"Stored last migrated employee record - pk={employee_record.pk}",
    ]
    reject.refresh_from_db()
    assert reject.timestamp != schedule1.timestamp
    process.refresh_from_db()
    assert process.timestamp != schedule2.timestamp

    assert list(employee_record.logs.order_by("timestamp", "pk").values_list("transition", flat=True)) == [
        EmployeeRecordTransition.SCHEDULE_MODIFICATION,
        EmployeeRecordTransition.WAIT_FOR_MODIFICATION_ASP_RESPONSE,
        EmployeeRecordTransition.REJECT_MODIFICATION,
        EmployeeRecordTransition.SCHEDULE_MODIFICATION,
        EmployeeRecordTransition.WAIT_FOR_MODIFICATION_ASP_RESPONSE,
        EmployeeRecordTransition.PROCESS_MODIFICATION,
    ]

    # Relaunching the command a few extra times doesn't update anything
    caplog.clear()
    call_command("fix_migrated_employee_record_transition_logs", wet_run=True)
    assert process_output(caplog.messages) == [
        f"Starting fixing transition logs of employee records - starting at pk={employee_record.pk}",
        "Checked 0 EmployeeRecord and fixed 0 EmployeeRecordTransitionLog",
        "Stored last migrated employee record - pk=0",
    ]
    caplog.clear()
    call_command("fix_migrated_employee_record_transition_logs", wet_run=True)
    assert process_output(caplog.messages) == [
        "Starting fixing transition logs of employee records - starting at pk=0",
        "Checked 1 EmployeeRecord and fixed 0 EmployeeRecordTransitionLog",
        f"Stored last migrated employee record - pk={employee_record.pk}",
    ]
