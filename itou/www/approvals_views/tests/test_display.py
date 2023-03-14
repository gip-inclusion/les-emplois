from unittest.mock import PropertyMock, patch

import pytest
from dateutil.relativedelta import relativedelta
from django.urls import reverse

from itou.approvals.enums import Origin
from itou.approvals.factories import ApprovalFactory
from itou.job_applications.factories import JobApplicationFactory
from itou.job_applications.models import JobApplication
from itou.siaes.factories import SiaeMembershipFactory
from itou.utils import constants as global_constants
from itou.utils.test import TestCase


@patch.object(JobApplication, "can_be_cancelled", new_callable=PropertyMock, return_value=False)
class TestDisplayApproval(TestCase):
    def test_display_job_app_approval(self, *args, **kwargs):
        job_application = JobApplicationFactory(with_approval=True)

        siae_member = job_application.to_siae.members.first()
        self.client.force_login(siae_member)

        response = self.client.get(
            reverse("approvals:display_printable_approval", kwargs={"approval_id": job_application.approval_id})
        )

        assert response.status_code == 200
        assert response.context["approval"] == job_application.approval
        assert response.context["siae"] == job_application.to_siae
        self.assertContains(response, global_constants.ITOU_ASSISTANCE_URL)
        self.assertContains(response, "Imprimer ce PASS IAE")
        self.assertContains(response, "Astuce pour conserver cette attestation en format PDF")

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

        assert response.status_code == 200
        assert response.context["approval"] == job_application.approval
        assert response.context["siae"] == job_application.to_siae
        self.assertContains(response, global_constants.ITOU_ASSISTANCE_URL)
        self.assertContains(response, "Imprimer ce PASS IAE")
        self.assertContains(response, "Astuce pour conserver cette attestation en format PDF")

    def test_dont_display_approval_with_no_eligibility_diagnosis_and_no_job_applications(self, *args, **kwargs):
        approval = ApprovalFactory(eligibility_diagnosis=None)
        siae_member = SiaeMembershipFactory().user
        self.client.force_login(siae_member)

        response = self.client.get(
            reverse("approvals:display_printable_approval", kwargs={"approval_id": approval.pk})
        )

        assert response.status_code == 404

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

        assert response.status_code == 200
        assert response.context["approval"] == job_application.approval
        assert response.context["siae"] == job_application.to_siae
        self.assertContains(response, global_constants.ITOU_ASSISTANCE_URL)
        self.assertContains(response, "Imprimer ce PASS IAE")
        self.assertContains(response, "Astuce pour conserver cette attestation en format PDF")

    def test_display_approval_missing_diagnosis_ai_job_application(self, *args, **kwargs):
        # TODO(alaurent) remove once last approvals were manually fixed
        # On November 30th, 2021, AI were delivered approvals without a diagnosis.
        job_application = JobApplicationFactory(
            with_approval=True,
            eligibility_diagnosis=None,
            origin=Origin.AI_STOCK,
        )

        siae_member = job_application.to_siae.members.first()
        self.client.force_login(siae_member)

        response = self.client.get(
            reverse("approvals:display_printable_approval", kwargs={"approval_id": job_application.approval_id})
        )

        assert response.status_code == 200
        assert response.context["approval"] == job_application.approval
        assert response.context["siae"] == job_application.to_siae
        self.assertContains(response, global_constants.ITOU_ASSISTANCE_URL)
        self.assertContains(response, "Imprimer ce PASS IAE")
        self.assertContains(response, "Astuce pour conserver cette attestation en format PDF")

    def test_display_approval_missing_diagnosis_ai_approval(self, *args, **kwargs):
        # TODO(alaurent) remove once last approvals were manually fixed
        # On November 30th, 2021, AI were delivered approvals without a diagnosis.
        job_application = JobApplicationFactory(
            with_approval=True,
            eligibility_diagnosis=None,
            approval__origin=Origin.AI_STOCK,
        )

        siae_member = job_application.to_siae.members.first()
        self.client.force_login(siae_member)

        response = self.client.get(
            reverse("approvals:display_printable_approval", kwargs={"approval_id": job_application.approval_id})
        )

        assert response.status_code == 200
        assert response.context["approval"] == job_application.approval
        assert response.context["siae"] == job_application.to_siae
        self.assertContains(response, global_constants.ITOU_ASSISTANCE_URL)
        self.assertContains(response, "Imprimer ce PASS IAE")
        self.assertContains(response, "Astuce pour conserver cette attestation en format PDF")

    def test_no_display_if_missing_diagnosis(self, *args, **kwargs):
        """
        Given an existing job application with an approval delivered by Itou but no
        diagnosis, when trying to display it as printable, then it raises an error.
        """
        job_application = JobApplicationFactory(with_approval=True, eligibility_diagnosis=None)

        siae_member = job_application.to_siae.members.first()
        self.client.force_login(siae_member)

        with pytest.raises(Exception, match="had no eligibility diagnosis and also was not mass-imported"):
            self.client.get(
                reverse("approvals:display_printable_approval", kwargs={"approval_id": job_application.approval_id})
            )
