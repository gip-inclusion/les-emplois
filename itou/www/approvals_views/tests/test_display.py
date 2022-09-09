from unittest.mock import PropertyMock, patch

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from itou.job_applications.factories import JobApplicationFactory, JobApplicationWithApprovalFactory
from itou.job_applications.models import JobApplication
from itou.users.factories import UserFactory
from itou.utils import constants as global_constants


@patch.object(JobApplication, "can_be_cancelled", new_callable=PropertyMock, return_value=False)
class TestDisplayApproval(TestCase):
    def test_display_job_app_approval(self, *args, **kwargs):
        job_application = JobApplicationWithApprovalFactory()

        siae_member = job_application.to_siae.members.first()
        self.client.force_login(siae_member)

        response = self.client.get(
            reverse("approvals:display_printable_approval", kwargs={"job_application_id": job_application.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["approval"], job_application.approval)
        self.assertEqual(response.context["siae"], job_application.to_siae)
        self.assertEqual(response.context["job_seeker"], job_application.job_seeker)
        self.assertContains(response, global_constants.ITOU_ASSISTANCE_URL)
        self.assertContains(response, "Imprimer ce PASS IAE")
        self.assertContains(response, "Astuce pour conserver cette attestation en format PDF")

    def test_impossible_display_when_approval_is_missing(self, *args, **kwargs):
        job_application = JobApplicationFactory()

        siae_member = job_application.to_siae.members.first()
        self.client.force_login(siae_member)

        response = self.client.get(
            reverse("approvals:display_printable_approval", kwargs={"job_application_id": job_application.pk})
        )
        # `can_display_approval` should fail and trigger a 404.
        self.assertEqual(response.status_code, 404)

    def test_display_approval_even_if_diagnosis_is_missing(self, *args, **kwargs):
        # An approval has been delivered but it does not come from Itou.
        # Therefore, the linked diagnosis exists but is not in our database.
        job_application = JobApplicationWithApprovalFactory(
            eligibility_diagnosis=None, approval__number="625741810181"
        )

        siae_member = job_application.to_siae.members.first()
        self.client.force_login(siae_member)

        response = self.client.get(
            reverse("approvals:display_printable_approval", kwargs={"job_application_id": job_application.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["approval"], job_application.approval)
        self.assertEqual(response.context["siae"], job_application.to_siae)
        self.assertEqual(response.context["job_seeker"], job_application.job_seeker)
        self.assertContains(response, global_constants.ITOU_ASSISTANCE_URL)
        self.assertContains(response, "Imprimer ce PASS IAE")
        self.assertContains(response, "Astuce pour conserver cette attestation en format PDF")

    def test_display_approval_missing_diagnosis_ai(self, *args, **kwargs):
        # On November 30th, 2021, AI were delivered approvals without a diagnosis.
        # See itou.users.management.commands.import_ai_employees.
        approval_created_at = settings.AI_EMPLOYEES_STOCK_IMPORT_DATE
        approval_created_by = UserFactory(email=settings.AI_EMPLOYEES_STOCK_DEVELOPER_EMAIL)
        job_application = JobApplicationWithApprovalFactory(
            eligibility_diagnosis=None,
            approval__created_at=approval_created_at,
            approval__created_by=approval_created_by,
        )

        siae_member = job_application.to_siae.members.first()
        self.client.force_login(siae_member)

        response = self.client.get(
            reverse("approvals:display_printable_approval", kwargs={"job_application_id": job_application.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["approval"], job_application.approval)
        self.assertEqual(response.context["siae"], job_application.to_siae)
        self.assertEqual(response.context["job_seeker"], job_application.job_seeker)
        self.assertContains(response, global_constants.ITOU_ASSISTANCE_URL)
        self.assertContains(response, "Imprimer ce PASS IAE")
        self.assertContains(response, "Astuce pour conserver cette attestation en format PDF")

    def test_no_display_if_missing_diagnosis(self, *args, **kwargs):
        """
        Given an existing job application with an approval delivered by Itou but no
        diagnosis, when trying to display it as printable, then it raises an error.
        """
        job_application = JobApplicationWithApprovalFactory(eligibility_diagnosis=None)

        siae_member = job_application.to_siae.members.first()
        self.client.force_login(siae_member)

        with self.assertRaisesRegex(Exception, "had no eligibility diagnosis and also was not mass-imported"):
            self.client.get(
                reverse("approvals:display_printable_approval", kwargs={"job_application_id": job_application.pk})
            )
