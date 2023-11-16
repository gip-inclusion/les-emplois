import datetime

import pytest
from dateutil.relativedelta import relativedelta
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertNumQueries, assertRedirects

from itou.job_applications.enums import SenderKind
from itou.job_applications.models import JobApplicationWorkflow
from itou.utils.templatetags.format_filters import format_approval_number
from tests.approvals.factories import ApprovalFactory, ProlongationFactory, SuspensionFactory
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.eligibility.factories import EligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory, JobApplicationSentByPrescriberOrganizationFactory
from tests.prescribers.factories import PrescriberFactory, PrescriberOrganizationFactory
from tests.users.factories import JobSeekerFactory
from tests.utils.test import parse_response_to_soup


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
        EligibilityDiagnosisFactory(job_seeker=approval.user, author_siae=job_application.to_company)

        # Another job applcation on the same SIAE, by a non authorized prescriber
        same_siae_job_application = JobApplicationSentByPrescriberOrganizationFactory(
            job_seeker=job_application.job_seeker,
            to_company=job_application.to_company,
            state=JobApplicationWorkflow.STATE_NEW,
        )
        assert not same_siae_job_application.is_sent_by_authorized_prescriber
        # A third job application on another SIAE
        other_siae_job_application = JobApplicationFactory(job_seeker=job_application.job_seeker)

        employer = job_application.to_company.members.first()
        client.force_login(employer)

        url = reverse("approvals:detail", kwargs={"pk": approval.pk})
        response = client.get(url)
        assertContains(response, "Numéro de PASS IAE")
        assertContains(response, "Informations du salarié")
        assertContains(response, "Éligibilité à l'IAE")
        assertContains(response, "Candidatures de ce salarié")
        assertContains(response, "Voir sa candidature", count=2)
        assertContains(
            response, reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        )
        assertContains(
            response, reverse("apply:details_for_company", kwargs={"job_application_id": same_siae_job_application.pk})
        )
        assertNotContains(
            response,
            reverse("apply:details_for_company", kwargs={"job_application_id": other_siae_job_application.pk}),
        )
        assertContains(response, '<i class="ri-group-line me-2" aria-hidden="true"></i>Prescripteur habilité', count=1)
        assertContains(response, '<i class="ri-group-line me-2" aria-hidden="true"></i>Orienteur', count=1)

    def test_detail_view_no_job_application(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        # Make sure the job seeker infos can be edited by the siae member
        approval = ApprovalFactory(user__created_by=employer)
        EligibilityDiagnosisFactory(job_seeker=approval.user, author_siae=company)

        client.force_login(employer)

        url = reverse("approvals:detail", kwargs={"pk": approval.pk})
        response = client.get(url)
        # Check that the page didn't crash
        assertContains(response, "Numéro de PASS IAE")
        assertContains(response, "Informations du salarié")
        assertContains(response, "Candidatures de ce salarié")

    @freeze_time("2023-04-26")
    def test_approval_status_includes(self, client, snapshot):
        """
        templates/approvals/includes/status.html
        This template is used in approval views but also in many other places.
        Test its content only once.
        """
        job_application = JobApplicationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING,
            with_approval=True,
            approval__id=1,
            sent_by_authorized_prescriber_organisation=True,
        )
        approval = job_application.approval
        expected_num_queries = (
            1  # fetch django session
            + 1  # fetch authenticated user
            + 2  # fetch siae membership and siae infos (middleware)
            + 1  # place savepoint right after the middlewares
            + 1  # job_seeker.approval
            + 1  # job_application.with_accepted_at annotation coming from next query
            + 1  # approval.suspension active today
            + 1  # Suspension.can_be_handled_by_siae >> User.last_accepted_job_application
            + 1  # select latest approval for user (can_be_prolonged)
            + 1  # approval.remainder fetches approval suspensions to compute remaining days.
            + 1  # release savepoint before the template rendering
            + 1  # template: approval.pending_prolongation_request fetch the current pending prolongation request
            + 1  # template: approval.suspensions_for_status_card lists approval suspensions
            + 1  # template: approval prolongations list.
            + 1  # template: approval.prolongation_requests_for_status_card lists not accepted prolongation requests
            + 1  # get job_application details (view queryset)
            + 1  # get prefetch job_application selected_jobs
            + 1  # get sender information (prescriber organization details)
            + 1  # Create savepoint (atomic request to update the Django session)
            + 1  # Update the Django session
            + 1  # Release savepoint
        )

        # Employer version
        user = job_application.to_company.members.first()
        client.force_login(user)

        url = reverse("approvals:detail", kwargs={"pk": approval.pk})
        with assertNumQueries(expected_num_queries):
            response = client.get(url)
        response = client.get(url)
        assertContains(response, format_approval_number(approval))
        assertContains(response, approval.start_at.strftime("%d/%m/%Y"))
        assertContains(response, f"{approval.remainder.days} jours")
        assertNotContains(
            response,
            "PASS IAE valide jusqu’au 25/04/2025, si le contrat démarre aujourd’hui.",
        )

        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertContains(
            response,
            "PASS IAE valide jusqu’au 25/04/2025, si le contrat démarre aujourd’hui.",
        )
        assertNotContains(
            response,
            "Date de fin prévisionnelle : 25/04/2025",
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
            id=1,
            approval=approval,
            start_at=timezone.localdate() - relativedelta(days=7),
            end_at=timezone.localdate() + relativedelta(days=3),
        )
        # Older
        SuspensionFactory(
            id=2,
            approval=approval,
            start_at=timezone.localdate() - relativedelta(days=30),
            end_at=timezone.localdate() - relativedelta(days=20),
        )

        url = reverse("approvals:detail", kwargs={"pk": approval.pk})
        expected_num_queries = (
            1  # fetch django session
            + 1  # fetch authenticated user
            + 1  # fetch siae membership and siae infos (middleware)
            + 1  # place savepoint right after the middlewares
            + 1  # get approval infos (get_object)
            # get_context_data
            + 1  # for every *active* suspension, check if there is an accepted job application after it
            + 1  # approval.suspension_set.end_at >= today >= approval.suspension_set.start_at (.can_be_suspended)
            + 1  # job_application.with_accepted_at annotation coming from (.last_hire_was_made_by_company)
            + 1  # siae infos (.last_hire_was_made_by_company)
            + 1  # user approvals (.is_last_for_user)
            + 1  # siae infos (job_application.get_eligibility_diagnosis())
            + 1  # approval.suspensions_for_status_card lists approval suspensions
            + 1  # EXISTS accepted job application starting after today
            + 1  # release savepoint before the template rendering
            # context processors
            + 1  # siae membership (get_context_siae)
            # template: approvals/includes/status.html
            + 1  # template: approval.remainder fetches approval suspensions to compute remaining days
            + 1  # template: approval.pending_prolongation_request fetch the current pending prolongation request
            + 1  # template: approval.prolongations_for_status_card
            + 1  # template: approval.prolongation_requests_for_status_card lists not accepted prolongation requests
            # template: eligibility_diagnosis.html
            + 1  # prescribers_prescriberorganization (job_application.is_sent_by_authorized_prescriber)
            + 1  # get user infos (eligibility_diagnosis.author.get_full_name)
            + 1  # eligibility_diagnosis.administrative_criteria.all
            + 3  # approval: eligibility_diagnosis.considered_to_expire_at/has_valid_common_approval
            # template: approvals/detail.html
            + 2  # all_job_applications with prefetch selected_jobs
            # template: approvals/includes/job_description_list.html
            + 1  # prescriberorganization: job_application.sender_prescriber_organization
        )

        with assertNumQueries(expected_num_queries):
            response = client.get(url)

        suspensions_section = parse_response_to_soup(response, selector="#suspensions-list")
        assert str(suspensions_section) == snapshot(name="Approval suspensions list")

        approval.suspension_set.all().delete()

        ## Display prolongations
        default_kwargs = {
            "declared_by": PrescriberFactory(first_name="Milady", last_name="de Winter", email="milady@dewinter.com"),
            "validated_by": None,
            "approval": approval,
        }
        # Valid
        active_prolongation = ProlongationFactory(
            id=1,
            start_at=timezone.localdate() - relativedelta(days=7),
            end_at=timezone.localdate() + relativedelta(days=3),
            **default_kwargs,
        )

        # Older
        ProlongationFactory(
            id=2,
            start_at=timezone.localdate() - relativedelta(days=30),
            end_at=timezone.localdate() - relativedelta(days=20),
            **default_kwargs,
        )
        ProlongationFactory(
            id=3,
            start_at=timezone.localdate() - relativedelta(days=60),
            end_at=timezone.localdate() - relativedelta(days=50),
            **default_kwargs,
        )

        # In the future
        ProlongationFactory(
            id=4,
            start_at=active_prolongation.end_at + relativedelta(days=10),
            end_at=active_prolongation.end_at + relativedelta(days=15),
            **default_kwargs,
        )

        url = reverse("approvals:detail", kwargs={"pk": approval.pk})
        # 1 query less to be executed: no more suspensions so no more need to check if there
        # is an accepted job application
        with assertNumQueries(expected_num_queries - 1):
            response = client.get(url)

        prolongations_section = parse_response_to_soup(response, selector="#prolongations-list")
        assert str(prolongations_section) == snapshot(name="Approval prolongations list")

        # Prescriber version
        user = job_application.sender
        client.force_login(user)

        url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertNotContains(
            response,
            "PASS IAE valide jusqu’au 30/05/2025, si le contrat démarre aujourd’hui.",
        )

        assertContains(
            response,
            "Date de fin prévisionnelle : 30/05/2025",
        )

    def test_suspend_button(self, client):
        approval = ApprovalFactory(with_jobapplication=True)
        job_application = approval.jobapplication_set.get()
        siae = job_application.to_company
        employer = siae.members.first()
        client.force_login(employer)

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
        # any SIAE can prolong an approval (if it can be prolonged)
        approval = ApprovalFactory(
            with_jobapplication=True,
            start_at=timezone.localdate() - relativedelta(months=12),
            end_at=timezone.localdate() + relativedelta(months=2),
        )
        job_application = approval.jobapplication_set.get()
        siae = job_application.to_company
        employer = siae.members.first()
        client.force_login(employer)

        url = reverse("approvals:detail", kwargs={"pk": approval.pk})
        assert approval.can_be_prolonged
        response = client.get(url)
        assertContains(response, reverse("approvals:declare_prolongation", kwargs={"approval_id": approval.id}))

        approval.end_at = timezone.localdate() - relativedelta(months=4)
        approval.save()
        # Clear cached property
        del approval.can_be_prolonged
        assert not approval.can_be_prolonged
        response = client.get(url)
        assertNotContains(response, reverse("approvals:declare_prolongation", kwargs={"approval_id": approval.id}))

    @override_settings(TALLY_URL="https://tally.so")
    def test_edit_user_info_button(self, client):
        approval = ApprovalFactory(with_jobapplication=True)
        job_application = approval.jobapplication_set.get()
        employer = job_application.to_company.members.first()
        client.force_login(employer)
        url = reverse("approvals:detail", kwargs={"pk": approval.pk})

        user_info_edit_url = reverse(
            "dashboard:edit_job_seeker_info", kwargs={"job_seeker_pk": job_application.job_seeker_id}
        )
        user_info_edit_url = f"{user_info_edit_url}?back_url={url}&from_application={job_application.pk}"
        user_info_not_allowed = "Vous ne pouvez pas modifier ses informations"

        response = client.get(url)
        assertNotContains(response, user_info_edit_url)
        assertContains(response, user_info_not_allowed)

        job_application.job_seeker.created_by = PrescriberFactory()
        job_application.job_seeker.save()
        response = client.get(url)
        assertContains(response, user_info_edit_url)
        assertNotContains(response, user_info_not_allowed)

        # Check that the edit user link correctly displays the Tally link (thanks to from_application= parameter)
        response = client.get(user_info_edit_url)
        assertContains(
            response,
            (
                f'<a href="https://tally.so/r/wzxQlg?jobapplication={job_application.pk}" target="_blank" '
                f'rel="noopener">Demander la correction du numéro de sécurité sociale</a>'
            ),
            html=True,
        )

    @freeze_time("2023-04-26")
    @pytest.mark.usefixtures("unittest_compatibility")
    @override_settings(TALLY_URL="https://tally.so")
    def test_remove_approval_button(self, client):
        membership = CompanyMembershipFactory(
            user__id=123456,
            user__email="oph@dewinter.com",
            user__first_name="Milady",
            user__last_name="de Winter",
            company__id=999999,
            company__name="ACI de la Rochelle",
        )
        job_application = JobApplicationFactory(
            hiring_start_at=datetime.date(2021, 3, 1),
            to_company=membership.company,
            job_seeker=JobSeekerFactory(last_name="John", first_name="Doe"),
            with_approval=True,
            # Don't set an ASP_ITOU_PREFIX (see approval.save for details)
            approval__number="XXXXX1234568",
        )

        client.force_login(membership.user)

        # suspension still active, more than 1 year old, starting after the accepted job application
        suspension = SuspensionFactory(approval=job_application.approval, start_at=datetime.date(2022, 4, 8))
        response = client.get(reverse("approvals:detail", kwargs={"pk": job_application.approval.pk}))

        delete_button = parse_response_to_soup(response, selector="#approval-deletion-link")
        assert str(delete_button) == self.snapshot(name="bouton de suppression d'un PASS IAE")

        # suspension now is inactive
        suspension.end_at = datetime.date(2023, 4, 10)  # more than 12 months but ended
        suspension.save(update_fields=["end_at"])
        response = client.get(reverse("approvals:detail", kwargs={"pk": job_application.approval.pk}))

        delete_button = parse_response_to_soup(response, selector="#approval-deletion-link")
        assert str(delete_button) == self.snapshot(name="bouton de suppression d'un PASS IAE")
