from django.contrib import messages
from django.contrib.admin import helpers
from django.urls import reverse
from pytest_django.asserts import assertContains

from itou.employee_record import models as employee_record_models
from itou.job_applications import models
from tests.companies.factories import CompanyFactory
from tests.employee_record import factories as employee_record_factories
from tests.job_applications import factories
from tests.users.factories import JobSeekerFactory
from tests.utils.test import assertMessages


def test_create_employee_record(admin_client):
    job_application = factories.JobApplicationFactory(
        state=models.JobApplicationWorkflow.STATE_ACCEPTED,
        with_approval=True,
    )

    response = admin_client.post(
        reverse("admin:job_applications_jobapplication_changelist"),
        {
            "action": "create_employee_record",
            helpers.ACTION_CHECKBOX_NAME: [job_application.pk],
        },
    )

    employee_record = employee_record_models.EmployeeRecord.objects.get()
    assert employee_record.job_application == job_application

    url = reverse("admin:employee_record_employeerecord_change", args=[employee_record.pk])
    assertMessages(response, [(messages.SUCCESS, f'1 fiche salarié créée : <a href="{url}">{employee_record.pk}</a>')])


def test_create_employee_record_when_it_already_exists(admin_client):
    employee_record = employee_record_factories.EmployeeRecordFactory()
    job_application = employee_record.job_application

    response = admin_client.post(
        reverse("admin:job_applications_jobapplication_changelist"),
        {
            "action": "create_employee_record",
            helpers.ACTION_CHECKBOX_NAME: [job_application.pk],
        },
    )

    url = reverse("admin:job_applications_jobapplication_change", args=[job_application.pk])
    assertMessages(response, [(messages.WARNING, f'1 candidature ignorée : <a href="{url}">{job_application.pk}</a>')])


def test_create_job_application_does_not_crash(admin_client):
    job_seeker = JobSeekerFactory()
    company = CompanyFactory()
    response = admin_client.post(
        reverse("admin:job_applications_jobapplication_add"),
        {
            "state": "new",
            "job_seeker": job_seeker.pk,
            "to_company": company.pk,
            "sender_kind": "prescriber",
            "sender_company": "invalid value that should have been a pk",
        },
    )
    assertContains(response, "Corrigez les erreurs ci-dessous")
    assertContains(response, "Emetteur prescripteur manquant")
