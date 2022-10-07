from unittest import mock

from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from itou.approvals.factories import ApprovalFactory
from itou.eligibility.factories import EligibilityDiagnosisFactory
from itou.job_applications.enums import SenderKind
from itou.job_applications.factories import JobApplicationFactory, JobApplicationSentByPrescriberOrganizationFactory
from itou.job_applications.models import JobApplicationWorkflow
from itou.prescribers.factories import PrescriberOrganizationFactory


class TestApprovalDetailView:
    def test_detail_view(self, client):
        approval = ApprovalFactory()
        job_application = JobApplicationFactory(
            approval=approval,
            job_seeker=approval.user,
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            # Make job application.is_sent_by_authorized_prescriber to be true
            sender_kind=SenderKind.PRESCRIBER,
            sender_prescriber_organization=PrescriberOrganizationFactory(authorized=True),
        )
        assert job_application.is_sent_by_authorized_prescriber
        EligibilityDiagnosisFactory(job_seeker=approval.user, author_siae=job_application.to_siae)

        # Another job applcation on the same SIAE, by a non authorized prescriber
        same_siae_job_application = JobApplicationSentByPrescriberOrganizationFactory(
            job_seeker=job_application.job_seeker,
            to_siae=job_application.to_siae,
            state=JobApplicationWorkflow.STATE_NEW,
        )
        assert not same_siae_job_application.is_sent_by_authorized_prescriber
        # A third job application on another SIAE
        other_siae_job_application = JobApplicationFactory(job_seeker=job_application.job_seeker)

        siae_member = job_application.to_siae.members.first()
        client.force_login(siae_member)

        url = reverse("approvals:detail", kwargs={"pk": approval.pk})
        response = client.get(url)
        assertContains(response, "PASS IAE (agrément) disponible")
        assertContains(response, "Informations du salarié")
        assertContains(response, "Éligibilité à l'IAE")
        assertContains(response, "Candidatures de ce salarié")
        assertContains(response, "Voir sa candidature", count=2)
        assertContains(response, reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk}))
        assertContains(
            response, reverse("apply:details_for_siae", kwargs={"job_application_id": same_siae_job_application.pk})
        )
        assertNotContains(
            response, reverse("apply:details_for_siae", kwargs={"job_application_id": other_siae_job_application.pk})
        )
        assertContains(response, '<i class="ri-group-line ml-2" aria-hidden="true"></i> Prescripteur', count=1)
        assertContains(response, '<i class="ri-group-line ml-2" aria-hidden="true"></i> Orienteur', count=1)

    def test_suspend_button(self, client):
        approval = ApprovalFactory(with_jobapplication=True)
        job_application = approval.jobapplication_set.get()
        siae_member = job_application.to_siae.members.first()
        client.force_login(siae_member)

        url = reverse("approvals:detail", kwargs={"pk": approval.pk})
        with mock.patch("itou.approvals.models.Approval.can_be_suspended_by_siae", return_value=True):
            response = client.get(url)
            assertContains(response, reverse("approvals:suspend", kwargs={"approval_id": approval.id}))
        with mock.patch("itou.approvals.models.Approval.can_be_suspended_by_siae", return_value=False):
            response = client.get(url)
            assertNotContains(response, reverse("approvals:suspend", kwargs={"approval_id": approval.id}))

    def test_prolongation_button(self, client):
        approval = ApprovalFactory(with_jobapplication=True)
        job_application = approval.jobapplication_set.get()
        siae_member = job_application.to_siae.members.first()
        client.force_login(siae_member)

        url = reverse("approvals:detail", kwargs={"pk": approval.pk})
        with mock.patch("itou.approvals.models.Approval.can_be_prolonged_by_siae", return_value=True):
            response = client.get(url)
            assertContains(response, reverse("approvals:declare_prolongation", kwargs={"approval_id": approval.id}))
        with mock.patch("itou.approvals.models.Approval.can_be_prolonged_by_siae", return_value=False):
            response = client.get(url)
            assertNotContains(response, reverse("approvals:declare_prolongation", kwargs={"approval_id": approval.id}))

    def test_edit_user_info_button(self, client):
        approval = ApprovalFactory(with_jobapplication=True)
        job_application = approval.jobapplication_set.get()
        siae_member = job_application.to_siae.members.first()
        client.force_login(siae_member)

        url = reverse("approvals:detail", kwargs={"pk": approval.pk})
        with mock.patch(
            "itou.job_applications.models.JobApplication.has_editable_job_seeker",
            property(mock.Mock(return_value=True)),
        ):
            response = client.get(url)
            assertContains(response, "Modifier les informations personnelles")
            assertNotContains(response, "Vous ne pouvez pas modifier ses informations")
        with mock.patch(
            "itou.job_applications.models.JobApplication.has_editable_job_seeker",
            property(mock.Mock(return_value=False)),
        ):
            response = client.get(url)
            assertNotContains(response, "Modifier les informations personnelles")
            assertContains(response, "Vous ne pouvez pas modifier ses informations")
