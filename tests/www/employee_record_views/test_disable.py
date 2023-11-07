import pytest
from django.urls import reverse
from django.utils.html import escape

from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecord
from tests.companies.factories import CompanyWithMembershipAndJobsFactory
from tests.employee_record.factories import EmployeeRecordWithProfileFactory
from tests.job_applications.factories import JobApplicationWithCompleteJobSeekerProfileFactory
from tests.utils.test import TestCase


pytestmark = pytest.mark.ignore_template_errors


@pytest.mark.usefixtures("unittest_compatibility")
class DisableEmployeeRecordsTest(TestCase):
    def setUp(self):
        super().setUp()
        # User must be super user for UI first part (tmp)
        self.company = CompanyWithMembershipAndJobsFactory(name="Wanna Corp.", membership__user__first_name="Billy")
        self.user = self.company.members.get(first_name="Billy")
        self.job_application = JobApplicationWithCompleteJobSeekerProfileFactory(to_siae=self.company)
        self.employee_record = EmployeeRecordWithProfileFactory(job_application=self.job_application)
        self.url = reverse("employee_record_views:disable", args=(self.employee_record.id,))
        self.next_url = reverse("employee_record_views:list")

    def test_access_granted(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_disable_employee_record_new(self):
        assert self.employee_record.status == Status.NEW

        self.client.force_login(self.user)
        response = self.client.get(f"{self.url}?status=NEW")
        self.assertContains(response, "Confirmer la désactivation")

        response = self.client.post(f"{self.url}?status=NEW", data={"confirm": "true"}, follow=True)
        self.assertRedirects(response, f"{self.next_url}?status=NEW")
        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.DISABLED

    def test_disable_employee_record_ready(self):
        self.employee_record.update_as_ready()

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.READY

        self.client.force_login(self.user)
        response = self.client.get(f"{self.url}?status=READY", follow=True)
        self.assertRedirects(response, f"{self.next_url}?status=READY")
        self.assertContains(response, escape(EmployeeRecord.ERROR_EMPLOYEE_RECORD_INVALID_STATE))

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.READY

    def test_disable_employee_record_sent(self):
        self.employee_record.update_as_ready()
        self.employee_record.update_as_sent(self.faker.asp_batch_filename(), 1, None)

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.SENT

        self.client.force_login(self.user)
        response = self.client.get(f"{self.url}?status=SENT", follow=True)
        self.assertRedirects(response, f"{self.next_url}?status=SENT")
        self.assertContains(response, escape(EmployeeRecord.ERROR_EMPLOYEE_RECORD_INVALID_STATE))

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.SENT

    def test_disable_employee_record_rejected(self):
        self.employee_record.update_as_ready()
        self.employee_record.update_as_sent(self.faker.asp_batch_filename(), 1, None)
        err_code, err_message = "12", "JSON Invalide"
        self.employee_record.update_as_rejected(err_code, err_message, None)

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.REJECTED

        self.client.force_login(self.user)
        response = self.client.get(f"{self.url}?status=REJECTED")
        self.assertContains(response, "Confirmer la désactivation")

        response = self.client.post(f"{self.url}?status=REJECTED", data={"confirm": "true"}, follow=True)
        self.assertRedirects(response, f"{self.next_url}?status=REJECTED")

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.DISABLED

    def test_disable_employee_record_completed(self):
        self.employee_record.update_as_ready()
        self.employee_record.update_as_sent(self.faker.asp_batch_filename(), 1, None)
        process_code, process_message = "0000", "La ligne de la fiche salarié a été enregistrée avec succès."
        self.employee_record.update_as_processed(process_code, process_message, "{}")

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.PROCESSED

        self.client.force_login(self.user)
        response = self.client.get(f"{self.url}?status=PROCESSED")
        self.assertContains(response, "Confirmer la désactivation")

        response = self.client.post(f"{self.url}?status=PROCESSED", data={"confirm": "true"}, follow=True)
        self.assertRedirects(response, f"{self.next_url}?status=PROCESSED")

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.DISABLED
