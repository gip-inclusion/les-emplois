from django.urls import reverse

from itou.employee_record.enums import Status
from itou.employee_record.factories import EmployeeRecordWithProfileFactory
from itou.job_applications.factories import JobApplicationWithCompleteJobSeekerProfileFactory
from itou.siaes.factories import SiaeWithMembershipAndJobsFactory
from itou.utils.test import TestCase


class ReactivateEmployeeRecordsTest(TestCase):
    def setUp(self):
        # User must be super user for UI first part (tmp)
        self.siae = SiaeWithMembershipAndJobsFactory(
            name="Wanna Corp.", membership__user__first_name="Billy", membership__user__is_superuser=True
        )
        self.user = self.siae.members.get(first_name="Billy")
        self.job_application = JobApplicationWithCompleteJobSeekerProfileFactory(to_siae=self.siae)
        self.employee_record = EmployeeRecordWithProfileFactory(job_application=self.job_application)
        self.url = reverse("employee_record_views:reactivate", args=(self.employee_record.id,))
        self.next_url = reverse("employee_record_views:list")

    def test_reactivate_employee_record(self):
        self.employee_record.update_as_ready()
        filename = "RIAE_FS_20210410130001.json"
        self.employee_record.update_as_sent(filename, 1)
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

        job_seeker_name = self.employee_record.job_seeker.get_full_name().title()

        response = self.client.get(f"{self.next_url}?status=NEW")
        self.assertContains(response, job_seeker_name)

        response = self.client.get(f"{self.next_url}?status=DISABLED")
        self.assertNotContains(response, job_seeker_name)
