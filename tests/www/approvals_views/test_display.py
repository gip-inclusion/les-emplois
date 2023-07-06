from unittest.mock import PropertyMock, patch

from dateutil.relativedelta import relativedelta
from django.urls import reverse
from freezegun import freeze_time

from itou.job_applications.models import JobApplication
from itou.utils import constants as global_constants
from tests.approvals.factories import ApprovalFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.siaes.factories import SiaeMembershipFactory
from tests.utils.test import TestCase


@patch.object(JobApplication, "can_be_cancelled", new_callable=PropertyMock, return_value=False)
class TestDisplayApproval(TestCase):
    @freeze_time("2023-04-26")
    def test_display_job_app_approval(self, *args, **kwargs):
        job_application = JobApplicationFactory(with_approval=True)

        siae_member = job_application.to_siae.members.first()
        self.client.force_login(siae_member)

        response = self.client.get(
            reverse("approvals:display_printable_approval", kwargs={"approval_id": job_application.approval_id})
        )

        assert response.context["approval"] == job_application.approval
        assert response.context["siae"] == job_application.to_siae
        self.assertContains(response, "le 26 avril 2023")
        self.assertContains(response, global_constants.ITOU_ASSISTANCE_URL)
        self.assertContains(response, "Imprimer ce PASS IAE")
        self.assertContains(response, "Astuce pour conserver cette attestation en format PDF")
        self.assertContains(response, job_application.approval.start_at.strftime("%d/%m/%Y"))
        self.assertContains(response, f"{job_application.approval.remainder.days} jours")

    def test_display_approval_multiple_job_applications(self, *args, **kwargs):
        job_application = JobApplicationFactory(with_approval=True)
        JobApplicationFactory(
            job_seeker=job_application.job_seeker,
            approval=job_application.approval,
            to_siae=job_application.to_siae,
            state=job_application.state,
            created_at=job_application.created_at - relativedelta(days=1),
        )

        siae_member = job_application.to_siae.members.first()
        self.client.force_login(siae_member)

        response = self.client.get(
            reverse("approvals:display_printable_approval", kwargs={"approval_id": job_application.approval_id})
        )

        assert response.context["approval"] == job_application.approval
        assert response.context["siae"] == job_application.to_siae
        self.assertContains(response, global_constants.ITOU_ASSISTANCE_URL)
        self.assertContains(response, "Imprimer ce PASS IAE")
        self.assertContains(response, "Astuce pour conserver cette attestation en format PDF")

    def test_display_approval_with_no_eligibility_diagnosis_and_no_job_applications(self, *args, **kwargs):
        approval = ApprovalFactory(eligibility_diagnosis=None)
        siae_member = SiaeMembershipFactory().user
        self.client.force_login(siae_member)

        response = self.client.get(
            reverse("approvals:display_printable_approval", kwargs={"approval_id": approval.pk})
        )
        assert response.status_code == 200

    def test_display_approval_even_if_diagnosis_is_missing(self, *args, **kwargs):
        # An approval has been delivered but it does not come from Itou.
        # Therefore, the linked diagnosis exists but is not in our database.
        job_application = JobApplicationFactory(
            with_approval=True, eligibility_diagnosis=None, approval__number="625741810181"
        )

        siae_member = job_application.to_siae.members.first()
        self.client.force_login(siae_member)

        response = self.client.get(
            reverse("approvals:display_printable_approval", kwargs={"approval_id": job_application.approval_id})
        )

        assert response.context["approval"] == job_application.approval
        assert response.context["siae"] == job_application.to_siae
        self.assertContains(response, global_constants.ITOU_ASSISTANCE_URL)
        self.assertContains(response, "Imprimer ce PASS IAE")
        self.assertContains(response, "Astuce pour conserver cette attestation en format PDF")
