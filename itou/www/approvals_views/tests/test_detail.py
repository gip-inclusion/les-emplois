from dateutil.relativedelta import relativedelta
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertNumQueries, assertRedirects

from itou.approvals.factories import ApprovalFactory, SuspensionFactory
from itou.eligibility.factories import EligibilityDiagnosisFactory
from itou.job_applications.enums import SenderKind
from itou.job_applications.factories import JobApplicationFactory, JobApplicationSentByPrescriberOrganizationFactory
from itou.job_applications.models import JobApplicationWorkflow
from itou.prescribers.factories import PrescriberFactory, PrescriberOrganizationFactory
from itou.utils.templatetags.format_filters import format_approval_number


class TestApprovalDetailView:
    def test_anonymous_user(self, client):
        approval = ApprovalFactory()
        url = reverse("approvals:detail", kwargs={"pk": approval.pk})
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

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
        assertContains(response, "PASS IAE disponible")
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
        assertContains(response, '<i class="ri-group-line mr-2" aria-hidden="true"></i>Prescripteur habilité', count=1)
        assertContains(response, '<i class="ri-group-line mr-2" aria-hidden="true"></i>Orienteur', count=1)

    @freeze_time("2023-04-26")
    def test_approval_status_includes(self, client):
        """
        templates/approvals/includes/status.html
        This template is used in approval views but also in many other places.
        Test its content only once.
        """
        job_application = JobApplicationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            with_approval=True,
            sent_by_authorized_prescriber_organisation=True,
        )
        approval = job_application.approval
        expected_num_queries = (
            1  # fetch django session
            + 1  # fetch authenticated user
            + 1  # verify user is active (middleware)
            + 2  # fetch siae membership and siae infos (middleware)
            + 1  # job_seeker.approval
            + 1  # approval.suspension_set.end_at >= today
            + 1  # job_application.with_accepted_at annotation coming from next query
            + 1  # template: Suspension.can_be_handled_by_siae >> User.last_accepted_job_application
            + 1  # template: job_application.get_eligibility_diagnosis => Siae.is_subject_to_eligibility_rules
            + 1  # template: approval.remainder fetches approval suspensions to compute remaining days.
            + 1  # template: approval.suspensions_for_status_card lists approval suspensions
            + 1  # template: approval prolongations list.
            + 1  # get job_application details (view queryset)
            + 1  # get prefetch job_application selected_jobs
            + 1  # get sender information (prescriber organization details)
            + 1  # Create savepoint (atomic request to update the Django session)
            + 1  # Update the Django session
            + 1  # Release savepoint
        )  # 19

        # Employer version
        user = job_application.to_siae.members.first()
        client.force_login(user)

        url = reverse("approvals:detail", kwargs={"pk": approval.pk})
        with assertNumQueries(expected_num_queries):  # pylint: disable=not-context-manager
            response = client.get(url)
        response = client.get(url)
        assertContains(response, format_approval_number(approval))
        assertContains(response, approval.start_at.strftime("%d/%m/%Y"))
        assertContains(response, str(approval.remainder.days))
        assertNotContains(
            response,
            "PASS IAE valide jusqu’au 25/04/2025, si le contrat démarre aujourd’hui.",
        )

        url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertContains(
            response,
            "PASS IAE valide jusqu’au 25/04/2025, si le contrat démarre aujourd’hui.",
        )

        job_application.state = JobApplicationWorkflow.STATE_ACCEPTED
        job_application.save()
        response = client.get(url)
        assertNotContains(
            response,
            "PASS IAE valide jusqu’au 25/04/2025, si le contrat démarre aujourd’hui.",
        )

        ## Display suspensions
        # Valid
        SuspensionFactory(
            approval=approval,
            start_at=timezone.localdate() - relativedelta(days=7),
            end_at=timezone.localdate() + relativedelta(days=3),
        )
        # Older
        SuspensionFactory(
            approval=approval,
            start_at=timezone.localdate() - relativedelta(days=30),
            end_at=timezone.localdate() - relativedelta(days=20),
        )

        url = reverse("approvals:detail", kwargs={"pk": approval.pk})
        # FIXME(cms)
        # There is a problem with queries numbers in this view but I was unable to resolve it quickly.
        # The problem seems to be in templates/apply/includes/eligibility_diagnosis.html.
        expected_num_queries += (
            4  # `eligibility_diagnosis.considered_to_expire_at`
            + 1  # eligibility_diagnosis.administrative_criteria.all
            + 1  # ?
        )
        with assertNumQueries(expected_num_queries):  # pylint: disable=not-context-manager
            response = client.get(url)

        # TODO(cms): maybe use a snapshot instead.
        assertContains(response, "Suspension en cours")
        assertContains(response, "du 19/04/2023 au 29/04/2023")
        assertContains(response, "Suspensions passées")
        assertContains(response, "du 27/03/2023 au 06/04/2023")
        assertContains(response, "Modifier")
        assertContains(response, "Annuler")

        # Prescriber version
        user = job_application.sender
        client.force_login(user)

        url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertNotContains(
            response,
            "PASS IAE valide jusqu’au 25/04/2025, si le contrat démarre aujourd’hui.",
        )

    def test_suspend_button(self, client):
        approval = ApprovalFactory(with_jobapplication=True)
        job_application = approval.jobapplication_set.get()
        siae = job_application.to_siae
        siae_member = siae.members.first()
        client.force_login(siae_member)

        url = reverse("approvals:detail", kwargs={"pk": approval.pk})
        assert approval.can_be_suspended_by_siae(siae)
        response = client.get(url)
        assertContains(response, reverse("approvals:suspend", kwargs={"approval_id": approval.id}))

        SuspensionFactory(
            approval=approval,
            start_at=timezone.localdate() - relativedelta(days=1),
            end_at=timezone.localdate() + relativedelta(days=1),
        )
        # Clear cached property
        del approval.can_be_suspended
        del approval.is_suspended
        assert not approval.can_be_suspended_by_siae(siae)
        response = client.get(url)
        assertNotContains(response, reverse("approvals:suspend", kwargs={"approval_id": approval.id}))

    def test_prolongation_button(self, client):
        approval = ApprovalFactory(
            with_jobapplication=True,
            start_at=timezone.localdate() - relativedelta(months=12),
            end_at=timezone.localdate() + relativedelta(months=2),
        )
        job_application = approval.jobapplication_set.get()
        siae = job_application.to_siae
        siae_member = siae.members.first()
        client.force_login(siae_member)

        url = reverse("approvals:detail", kwargs={"pk": approval.pk})
        assert approval.can_be_prolonged_by_siae(siae)
        response = client.get(url)
        assertContains(response, reverse("approvals:declare_prolongation", kwargs={"approval_id": approval.id}))

        approval.end_at = timezone.localdate() - relativedelta(months=4)
        approval.save()
        # Clear cached property
        del approval.can_be_prolonged
        assert not approval.can_be_prolonged_by_siae(siae)
        response = client.get(url)
        assertNotContains(response, reverse("approvals:declare_prolongation", kwargs={"approval_id": approval.id}))

    def test_edit_user_info_button(self, client):
        approval = ApprovalFactory(with_jobapplication=True)
        job_application = approval.jobapplication_set.get()
        siae_member = job_application.to_siae.members.first()
        client.force_login(siae_member)

        user_info_edit_url = reverse(
            "dashboard:edit_job_seeker_info", kwargs={"job_application_id": job_application.pk}
        )
        user_info_not_allowed = "Vous ne pouvez pas modifier ses informations"

        url = reverse("approvals:detail", kwargs={"pk": approval.pk})
        assert not job_application.has_editable_job_seeker
        response = client.get(url)
        assertNotContains(response, user_info_edit_url)
        assertContains(response, user_info_not_allowed)

        job_application.job_seeker.created_by = PrescriberFactory()
        job_application.job_seeker.save()
        assert job_application.has_editable_job_seeker
        response = client.get(url)
        assertContains(response, user_info_edit_url)
        assertNotContains(response, user_info_not_allowed)
