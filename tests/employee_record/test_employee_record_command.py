from django.core import management

from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord
from tests.employee_record import factories


def test_create_with_siret(caplog):
    er = factories.EmployeeRecordFactory(ready_for_transfer=True, job_application__to_company__siret="12345678901234")

    management.call_command(
        "employee_record",
        "create",
        er.job_application.pk,
        siret="12345678904321",
        wet_run=True,
    )
    assert (
        EmployeeRecord.objects.filter(
            job_application=er.job_application,
            siret="12345678904321",
        )
        .exclude(pk=er.pk)
        .exists()
    )
    assert "Management command itou.employee_record.management.commands.employee_record succeeded" in caplog.text


def test_create_with_siret_and_ready(caplog):
    er = factories.EmployeeRecordFactory(ready_for_transfer=True, job_application__to_company__siret="12345678901234")

    management.call_command(
        "employee_record",
        "create",
        er.job_application.pk,
        siret="12345678904321",
        ready=True,
        wet_run=True,
    )
    assert (
        EmployeeRecord.objects.filter(
            job_application=er.job_application,
            siret="12345678904321",
            status=Status.READY,
        )
        .exclude(pk=er.pk)
        .exists()
    )
    assert "Management command itou.employee_record.management.commands.employee_record succeeded" in caplog.text
