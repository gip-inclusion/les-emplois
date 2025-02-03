import pytest
from django.urls import reverse, reverse_lazy
from django.utils.html import escape
from pytest_django.asserts import assertContains, assertRedirects

from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord, EmployeeRecordTransition
from tests.companies.factories import CompanyWithMembershipAndJobsFactory
from tests.employee_record.factories import EmployeeRecordWithProfileFactory
from tests.job_applications.factories import JobApplicationWithCompleteJobSeekerProfileFactory


class TestDisableEmployeeRecords:
    NEXT_URL = reverse_lazy("employee_record_views:list")

    @pytest.fixture(autouse=True)
    def setup_method(self):
        # User must be super user for UI first part (tmp)
        self.company = CompanyWithMembershipAndJobsFactory(name="Wanna Corp.", membership__user__first_name="Billy")
        self.user = self.company.members.get(first_name="Billy")
        self.job_application = JobApplicationWithCompleteJobSeekerProfileFactory(to_company=self.company)
        self.employee_record = EmployeeRecordWithProfileFactory(job_application=self.job_application)
        self.url = reverse("employee_record_views:disable", args=(self.employee_record.id,))

    def test_access_granted(self, client):
        client.force_login(self.user)
        response = client.get(self.url)
        assert response.status_code == 200

    def test_disable_employee_record_new(self, client):
        assert self.employee_record.status == Status.NEW

        client.force_login(self.user)
        response = client.get(f"{self.url}?status=NEW")
        assertContains(response, "Confirmer la désactivation")

        response = client.post(f"{self.url}?status=NEW", data={"confirm": "true"}, follow=True)
        assertRedirects(response, f"{self.NEXT_URL}?status=NEW")
        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.DISABLED

    def test_disable_employee_record_ready(self, client):
        self.employee_record.ready()

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.READY

        client.force_login(self.user)
        response = client.get(f"{self.url}?status=READY", follow=True)
        assertRedirects(response, f"{self.NEXT_URL}?status=READY")
        assertContains(response, escape(EmployeeRecord.ERROR_EMPLOYEE_RECORD_INVALID_STATE))

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.READY

    def test_disable_employee_record_sent(self, client, faker):
        self.employee_record.ready()
        self.employee_record.wait_for_asp_response(file=faker.asp_batch_filename(), line_number=1, archive=None)

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.SENT

        client.force_login(self.user)
        response = client.get(f"{self.url}?status=SENT", follow=True)
        assertRedirects(response, f"{self.NEXT_URL}?status=SENT")
        assertContains(response, escape(EmployeeRecord.ERROR_EMPLOYEE_RECORD_INVALID_STATE))

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.SENT

    def test_disable_employee_record_rejected(self, client, faker):
        self.employee_record.ready()
        self.employee_record.wait_for_asp_response(file=faker.asp_batch_filename(), line_number=1, archive=None)
        err_code, err_message = "12", "JSON Invalide"
        self.employee_record.reject(code=err_code, label=err_message, archive=None)

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.REJECTED

        client.force_login(self.user)
        response = client.get(f"{self.url}?status=REJECTED")
        assertContains(response, "Confirmer la désactivation")

        response = client.post(f"{self.url}?status=REJECTED", data={"confirm": "true"}, follow=True)
        assertRedirects(response, f"{self.NEXT_URL}?status=REJECTED")

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.DISABLED

    def test_disable_employee_record_completed(self, client, faker):
        self.employee_record.ready()
        self.employee_record.wait_for_asp_response(file=faker.asp_batch_filename(), line_number=1, archive=None)
        process_code, process_message = "0000", "La ligne de la fiche salarié a été enregistrée avec succès."
        self.employee_record.process(code=process_code, label=process_message, archive={})

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.PROCESSED

        client.force_login(self.user)
        response = client.get(f"{self.url}?status=PROCESSED")
        assertContains(response, "Confirmer la désactivation")

        response = client.post(f"{self.url}?status=PROCESSED", data={"confirm": "true"}, follow=True)
        assertRedirects(response, f"{self.NEXT_URL}?status=PROCESSED")

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.DISABLED

    def test_transition_log(self, client):
        client.force_login(self.user)

        assert self.employee_record.logs.count() == 0
        client.post(self.url, data={"confirm": "true"}, follow=True)

        log = self.employee_record.logs.get()
        assert log.transition == EmployeeRecordTransition.DISABLE
        assert log.user == self.user
