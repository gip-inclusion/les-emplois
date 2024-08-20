import datetime

import pytest
from dateutil.relativedelta import relativedelta
from django.template.defaultfilters import urlencode
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertNumQueries, assertRedirects

from itou.job_applications.enums import JobApplicationState, SenderKind
from itou.utils.templatetags.format_filters import format_approval_number
from itou.utils.urls import add_url_params
from tests.approvals.factories import (
    ApprovalFactory,
    ProlongationFactory,
    ProlongationRequestFactory,
    SuspensionFactory,
)
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory, JobApplicationSentByPrescriberOrganizationFactory
from tests.prescribers.factories import PrescriberFactory, PrescriberOrganizationFactory
from tests.users.factories import JobSeekerFactory
from tests.utils.test import assert_previous_step, parse_response_to_soup


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
            state=JobApplicationState.ACCEPTED,
            # Make job application.is_sent_by_authorized_prescriber to be true
            sender_kind=SenderKind.PRESCRIBER,
            sender_prescriber_organization=PrescriberOrganizationFactory(authorized=True),
        )
        assert job_application.is_sent_by_authorized_prescriber
        IAEEligibilityDiagnosisFactory(
            from_prescriber=True, job_seeker=approval.user, author_siae=job_application.to_company
        )

        # Another job applcation on the same SIAE, by a non authorized prescriber
        same_siae_job_application = JobApplicationSentByPrescriberOrganizationFactory(
            job_seeker=job_application.job_seeker,
            to_company=job_application.to_company,
            state=JobApplicationState.NEW,
        )
        assert not same_siae_job_application.is_sent_by_authorized_prescriber
        # A third job application on another SIAE
        other_siae_job_application = JobApplicationFactory(job_seeker=job_application.job_seeker)

        employer = job_application.to_company.members.first()
        client.force_login(employer)

        url = add_url_params(
            reverse("approvals:detail", kwargs={"pk": approval.pk}), {"back_url": reverse("approvals:list")}
        )
        response = client.get(url)
        assertContains(response, "Numéro de PASS IAE")
        assertContains(response, "Informations du salarié")
        assertContains(response, "Éligibilité à l'IAE")
        assertContains(response, "Candidatures de ce salarié")
        assertContains(response, "Voir sa candidature", count=2)
        job_application_base_url = reverse(
            "apply:details_for_company", kwargs={"job_application_id": job_application.pk}
        )
        job_application_url = f"{job_application_base_url}?back_url={urlencode(url)}"
        assertContains(response, job_application_url)
        assertContains(
            response, reverse("apply:details_for_company", kwargs={"job_application_id": same_siae_job_application.pk})
        )
        other_siae_job_application_base_url = reverse(
            "apply:details_for_company", kwargs={"job_application_id": other_siae_job_application.pk}
        )
        other_siae_job_application_url = f"{other_siae_job_application_base_url}?back_url={urlencode(url)}"
        assertNotContains(response, other_siae_job_application_url)

        assert_previous_step(response, reverse("approvals:list"), back_to_list=True)

    def test_detail_view_no_job_application(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        # Make sure the job seeker infos can be edited by the siae member
        approval = ApprovalFactory(user__created_by=employer)
        IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=approval.user, author_siae=company)

        client.force_login(employer)

        url = reverse("approvals:detail", kwargs={"pk": approval.pk})
        response = client.get(url)
        # Check that the page didn't crash
        assertContains(response, "Numéro de PASS IAE")
        assertContains(response, "Informations du salarié")
        assertContains(response, "Candidatures de ce salarié")

    @pytest.mark.ignore_unknown_variable_template_error("with_matomo_event")
    @freeze_time("2023-04-26")
    def test_approval_status_includes(self, client, snapshot):
        """
        templates/approvals/includes/status.html
        This template is used in approval views but also in many other places.
        Test its content only once.
        """
        job_application = JobApplicationFactory(
            state=JobApplicationState.PROCESSING,
            with_approval=True,
            approval__id=1,
            sent_by_authorized_prescriber_organisation=True,
        )
        approval = job_application.approval

        # Employer version
        user = job_application.to_company.members.first()
        client.force_login(user)

        url = reverse("approvals:detail", kwargs={"pk": approval.pk})
        # 1.  SELECT django_session
        # 2.  SELECT users_user
        # 3.  SELECT company_membership
        # 4.  SELECT company_company
        # END of middleware
        # 5.  SAVEPOINT
        # 6.  SELECT approvals_approval (get_object)
        # 7.  SELECT approvals_suspension (prefetch)
        # 8.  SELECT approvals_prolongationrequest (prefetch)
        # 9.  SELECT job_applications_jobapplication (get_job_application)
        # 10. SELECT job_applications_jobapplication (last accepted job application, can_be_handled_by_siae)
        # 11. SELECT approvals_approval (latest approval for user, can_be_prolonged)
        # 12. SELECT approvals_suspension
        # 13. RELEASE SAVEPOINT
        # END of view, template rendering
        # 14. SELECT approvals_suspension
        # 15. SELECT approvals_prolongation
        # 16. SELECT approvals_prolongationrequest
        # 17. SELECT job_applications_jobapplication
        # 18. SELECT job_applications_jobapplication_selected_jobs (prefetch)
        # 19. SELECT prescribers_prescriberorganization (get sender information)
        # END of template rendering
        # CREATE SAVEPOINT (ATOMIC REQUEST TO UPDATE THE DJANGO SESSION)
        # UPDATE django_session
        # RELEASE SAVEPOINT
        with assertNumQueries(22):
            response = client.get(url)
        response = client.get(url)
        assertContains(response, format_approval_number(approval))
        assertContains(response, approval.start_at.strftime("%d/%m/%Y"))
        assertContains(response, approval.get_remainder_display())
        assertNotContains(
            response,
            "PASS IAE valide jusqu’au 24/04/2025, si le contrat démarre aujourd’hui.",
        )

        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertContains(
            response,
            "PASS IAE valide jusqu’au 24/04/2025, si le contrat démarre aujourd’hui.",
        )
        assertNotContains(
            response,
            "Date de fin prévisionnelle : 24/04/2025",
        )

        job_application.state = JobApplicationState.ACCEPTED
        job_application.processed_at = timezone.now()
        job_application.save()
        response = client.get(url)
        assertNotContains(
            response,
            "PASS IAE valide jusqu’au 24/04/2025, si le contrat démarre aujourd’hui.",
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
        # 1.  SELECT django_session
        # 2.  SELECT users_user
        # 3.  SELECT company_membership
        # 4.  SELECT company_company
        # END of middleware
        # 5.  SAVEPOINT
        # 6.  SELECT approvals_approval (get_object)
        # 7.  SELECT approvals_suspension (prefetch)
        # 8.  SELECT approvals_prolongationrequest (prefetch)
        # 9.  SELECT job_applications_jobapplication (get_job_application)
        # 10. SELECT approvals_approval
        # 11. SELECT companies_company
        # 12. SELECT approvals_suspension
        # 13. SELECT EXISTS job_applications_jobapplication
        # 14. RELEASE SAVEPOINT
        # END of view, template rendering
        # 15. SELECT approvals_suspension
        # 16. SELECT job_applications_jobapplication
        # 17. SELECT approvals_prolongation
        # 18. SELECT approvals_prolongationrequest
        # 19. SELECT users_user
        # 20. SELECT users_user
        # 21. SELECT eligibility_administrativecriteria
        # 22. SELECT approvals_approval
        # 23. SELECT EXISTS approvals_approval
        # 24. SELECT approvals_approval
        # 25. SELECT job_applications_jobapplication
        # 26. SELECT job_applications_jobapplication_selected_jobs (prefetch)
        # 27. SELECT prescribers_prescriberorganization (get sender information)
        # END of template rendering
        with assertNumQueries(27):
            response = client.get(url)

        suspensions_section = parse_response_to_soup(response, selector="#suspensions-list")
        assert str(suspensions_section) == snapshot(name="Approval suspensions list")

        approval.suspension_set.all().delete()

        prescriber = PrescriberFactory(first_name="Milady", last_name="de Winter", email="milady@dewinter.com")

        ## Display prolongations
        default_kwargs = {
            "declared_by": prescriber,
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

        ProlongationRequestFactory(
            declared_by=prescriber,
            validated_by=PrescriberFactory(
                first_name="First",
                last_name="Last",
                email="first@last.com",
            ),
            approval=approval,
            prescriber_organization=PrescriberOrganizationFactory(name="Organization", department="72"),
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
        # 1.  SELECT django_session
        # 2.  SELECT users_user
        # 3.  SELECT company_membership
        # 4.  SELECT company_company
        # END of middleware
        # 5.  SAVEPOINT
        # 6.  SELECT approvals_approval (get_object)
        # 7.  SELECT approvals_suspension (prefetch)
        # 8.  SELECT approvals_prolongationrequest (prefetch)
        # 9.  SELECT job_applications_jobapplication (get_job_application)
        # 10. SELECT job_applications_jobapplication (can_be_handled_by_siae)
        # 11. SELECT approvals_approval
        # 12. SELECT companies_company
        # 13. SELECT approvals_suspension
        # 14. RELEASE SAVEPOINT
        # END of view, template rendering
        # 15. SELECT approvals_suspension
        # 16. SELECT approvals_prolongation
        # 17. SELECT approvals_prolongationrequest
        # 18. SELECT users_user
        # 19. SELECT users_user
        # 20. SELECT eligibility_administrativecriteria
        # 21. SELECT approvals_approval
        # 22. SELECT EXISTS approvals_approval
        # 23. SELECT approvals_approval
        # 24. SELECT job_applications_jobapplication
        # 25. SELECT job_applications_jobapplication_selected_jobs (prefetch)
        # 26. SELECT prescribers_prescriberorganization (get sender information)
        # END of template rendering
        with assertNumQueries(26):
            response = client.get(url)

        prolongations_section = parse_response_to_soup(response, selector="#prolongations-list")
        assert str(prolongations_section) == snapshot(name="Approval prolongations list")

        # Prescriber version
        user = job_application.sender
        client.force_login(user)

        url = reverse(
            "apply:details_for_prescriber",
            kwargs={"job_application_id": job_application.pk},
        )
        response = client.get(url)
        assertNotContains(
            response,
            "PASS IAE valide jusqu’au 29/05/2025, si le contrat démarre aujourd’hui.",
        )

        assertContains(
            response,
            "Date de fin prévisionnelle : 29/05/2025",
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
        assertContains(
            response,
            reverse("approvals:declare_prolongation", kwargs={"approval_id": approval.id}),
        )

        approval.end_at = timezone.localdate() - relativedelta(months=4)
        approval.save()
        # Clear cached property
        del approval.can_be_prolonged
        assert not approval.can_be_prolonged
        response = client.get(url)
        assertNotContains(
            response,
            reverse("approvals:declare_prolongation", kwargs={"approval_id": approval.id}),
        )

    @override_settings(TALLY_URL="https://tally.so")
    def test_edit_user_info_button(self, client):
        approval = ApprovalFactory(with_jobapplication=True)
        job_application = approval.jobapplication_set.get()
        employer = job_application.to_company.members.first()
        client.force_login(employer)
        url = reverse("approvals:detail", kwargs={"pk": approval.pk})

        user_info_edit_url = reverse(
            "dashboard:edit_job_seeker_info",
            kwargs={"job_seeker_public_id": job_application.job_seeker.public_id},
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
