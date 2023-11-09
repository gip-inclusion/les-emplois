import pytest
from django.urls import reverse

from itou.employee_record.enums import Status
from itou.utils.templatetags import format_filters
from tests.companies.factories import CompanyWithMembershipAndJobsFactory
from tests.employee_record.factories import EmployeeRecordWithProfileFactory
from tests.job_applications.factories import JobApplicationWithCompleteJobSeekerProfileFactory
from tests.utils.test import TestCase


pytestmark = pytest.mark.ignore_template_errors


@pytest.mark.usefixtures("unittest_compatibility")
class ReactivateEmployeeRecordsTest(TestCase):
    def setUp(self):
        super().setUp()
        # User must be super user for UI first part (tmp)
        self.company = CompanyWithMembershipAndJobsFactory(name="Wanna Corp.", membership__user__first_name="Billy")
        self.user = self.company.members.get(first_name="Billy")
        self.job_application = JobApplicationWithCompleteJobSeekerProfileFactory(to_company=self.company)
        self.employee_record = EmployeeRecordWithProfileFactory(job_application=self.job_application)
        self.url = reverse("employee_record_views:reactivate", args=(self.employee_record.id,))
        self.next_url = reverse("employee_record_views:list")

    def test_reactivate_employee_record(self):
        self.employee_record.update_as_ready()
        self.employee_record.update_as_sent(self.faker.asp_batch_filename(), 1, None)
        process_code, process_message = "0000", "La ligne de la fiche salarié a été enregistrée avec succès."
        self.employee_record.update_as_processed(process_code, process_message, "{}")
        self.employee_record.update_as_disabled()

        self.client.force_login(self.user)
        response = self.client.get(f"{self.url}?status=DISABLED")
        self.assertContains(response, "Confirmer la réactivation")

        response = self.client.post(f"{self.url}?status=DISABLED", data={"confirm": "true"}, follow=True)
        self.assertRedirects(response, f"{self.next_url}?status=DISABLED")

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.NEW

        approval_number_formatted = format_filters.format_approval_number(self.employee_record.approval_number)

        response = self.client.get(f"{self.next_url}?status=NEW")
        self.assertContains(response, approval_number_formatted)

        response = self.client.get(f"{self.next_url}?status=DISABLED")
        self.assertNotContains(response, approval_number_formatted)
