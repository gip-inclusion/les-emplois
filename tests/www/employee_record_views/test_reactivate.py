import pytest
from django.urls import reverse, reverse_lazy
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecordTransition
from itou.utils.templatetags import format_filters
from tests.companies.factories import CompanyWithMembershipAndJobsFactory
from tests.employee_record.factories import EmployeeRecordWithProfileFactory
from tests.job_applications.factories import JobApplicationWithCompleteJobSeekerProfileFactory


class TestReactivateEmployeeRecords:
    NEXT_URL = reverse_lazy("employee_record_views:list")

    @pytest.fixture(autouse=True)
    def setup_method(self):
        # User must be super user for UI first part (tmp)
        self.company = CompanyWithMembershipAndJobsFactory(name="Wanna Corp.", membership__user__first_name="Billy")
        self.user = self.company.members.get(first_name="Billy")
        self.job_application = JobApplicationWithCompleteJobSeekerProfileFactory(to_company=self.company)
        self.employee_record = EmployeeRecordWithProfileFactory(
            status=Status.DISABLED, job_application=self.job_application
        )
        self.url = reverse("employee_record_views:reactivate", args=(self.employee_record.id,))

    def test_reactivate_employee_record(self, client, faker):
        client.force_login(self.user)

        response = client.get(f"{self.url}?status=DISABLED")
        assertContains(response, "Confirmer la réactivation")

        response = client.post(f"{self.url}?status=DISABLED", data={"confirm": "true"}, follow=True)
        assertRedirects(response, f"{self.NEXT_URL}?status=DISABLED")

        self.employee_record.refresh_from_db()
        assert self.employee_record.status == Status.NEW

        approval_number_formatted = format_filters.format_approval_number(self.employee_record.approval_number)

        response = client.get(f"{self.NEXT_URL}?status=NEW")
        assertContains(response, approval_number_formatted)

        response = client.get(f"{self.NEXT_URL}?status=DISABLED")
        assertNotContains(response, approval_number_formatted)

    def test_transition_log(self, client):
        client.force_login(self.user)

        assert self.employee_record.logs.count() == 0
        client.post(self.url, data={"confirm": "true"}, follow=True)

        log = self.employee_record.logs.get()
        assert log.transition == EmployeeRecordTransition.ENABLE
        assert log.user == self.user
