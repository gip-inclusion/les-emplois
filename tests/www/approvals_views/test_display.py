from unittest.mock import PropertyMock, patch

from dateutil.relativedelta import relativedelta
from django.urls import reverse
from freezegun import freeze_time

from itou.job_applications.models import JobApplication
from itou.utils import constants as global_constants
from tests.job_applications.factories import JobApplicationFactory
from tests.utils.test import TestCase


@patch.object(JobApplication, "can_be_cancelled", new_callable=PropertyMock, return_value=False)
class TestDisplayApproval(TestCase):
    WITH_DIAGNOSIS_STR = "Au vu du diagnostic individuel réalisé par"

    @freeze_time("2023-04-26")
    def test_display_job_app_approval(self, *args, **kwargs):
        job_application = JobApplicationFactory(with_approval=True)

        employer = job_application.to_company.members.first()
        self.client.force_login(employer)

        response = self.client.get(
            reverse("approvals:display_printable_approval", kwargs={"approval_id": job_application.approval_id})
        )

        assert response.context["approval"] == job_application.approval
        assert response.context["siae"] == job_application.to_company
        self.assertContains(response, "le 26 avril 2023")
        self.assertContains(response, global_constants.ITOU_HELP_CENTER_URL)
        self.assertContains(response, "Imprimer ce PASS IAE")
        self.assertContains(response, job_application.approval.start_at.strftime("%d/%m/%Y"))
        self.assertContains(response, job_application.approval.get_remainder_display())
        self.assertContains(response, self.WITH_DIAGNOSIS_STR)

    def test_display_approval_multiple_job_applications(self, *args, **kwargs):
        job_application = JobApplicationFactory(with_approval=True)
        JobApplicationFactory(
            job_seeker=job_application.job_seeker,
            approval=job_application.approval,
            to_company=job_application.to_company,
            state=job_application.state,
            created_at=job_application.created_at - relativedelta(days=1),
        )

        employer = job_application.to_company.members.first()
        self.client.force_login(employer)

        response = self.client.get(
            reverse("approvals:display_printable_approval", kwargs={"approval_id": job_application.approval_id})
        )

        assert response.context["approval"] == job_application.approval
        assert response.context["siae"] == job_application.to_company
        self.assertContains(response, global_constants.ITOU_HELP_CENTER_URL)
        self.assertContains(response, "Imprimer ce PASS IAE")
        self.assertContains(response, self.WITH_DIAGNOSIS_STR)

    def test_display_approval_even_if_diagnosis_is_missing(self, *args, **kwargs):
        # An approval has been delivered but it does not come from Itou.
        # Therefore, the linked diagnosis exists but is not in our database.
        job_application = JobApplicationFactory(
            with_approval=True, eligibility_diagnosis=None, approval__number="625741810181"
        )

        employer = job_application.to_company.members.first()
        self.client.force_login(employer)

        response = self.client.get(
            reverse("approvals:display_printable_approval", kwargs={"approval_id": job_application.approval_id})
        )

        assert response.context["approval"] == job_application.approval
        assert response.context["siae"] == job_application.to_company
        self.assertContains(response, global_constants.ITOU_HELP_CENTER_URL)
        self.assertContains(response, "Imprimer ce PASS IAE")
        self.assertNotContains(response, self.WITH_DIAGNOSIS_STR)
