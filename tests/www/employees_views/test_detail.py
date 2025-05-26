import datetime

from django.template.defaultfilters import urlencode
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.job_applications.enums import JobApplicationState, SenderKind
from itou.utils.immersion_facile import immersion_search_url
from itou.utils.templatetags import format_filters
from itou.utils.urls import add_url_params
from tests.approvals.factories import (
    ApprovalFactory,
)
from tests.companies.factories import CompanyFactory
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory, JobApplicationSentByPrescriberOrganizationFactory
from tests.prescribers.factories import PrescriberFactory, PrescriberOrganizationFactory
from tests.utils.test import assert_previous_step, assertSnapshotQueries, parse_response_to_soup, pretty_indented


class TestEmployeeDetailView:
    APPROVAL_NUMBER_LABEL = "Numéro de PASS IAE"

    def test_anonymous_user(self, client):
        approval = ApprovalFactory()
        url = reverse("employees:detail", kwargs={"public_id": approval.user.public_id})
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_detail_view(self, client, snapshot):
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
            from_employer=True, job_seeker=approval.user, author_siae=job_application.to_company
        )

        # Another job application on the same SIAE, by a non authorized prescriber
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
            reverse("employees:detail", kwargs={"public_id": approval.user.public_id}),
            {"back_url": reverse("approvals:list")},
        )
        with assertSnapshotQueries(snapshot(name="employee detail view")):
            response = client.get(url)
        assertContains(response, self.APPROVAL_NUMBER_LABEL)
        assertContains(response, reverse("approvals:details", kwargs={"public_id": approval.public_id}))
        assertContains(response, "Informations du salarié")
        assertContains(response, "Éligibilité à l'IAE", html=True)
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
        IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=approval.user)

        client.force_login(employer)

        url = reverse("employees:detail", kwargs={"public_id": approval.user.public_id})
        response = client.get(url)
        assert response.status_code == 404

    def test_detail_view_no_approval(self, client):
        company = CompanyFactory(with_membership=True, subject_to_eligibility=True)
        employer = company.members.first()

        job_seeker = JobApplicationFactory(to_company=company, state=JobApplicationState.ACCEPTED).job_seeker

        client.force_login(employer)
        url = reverse("employees:detail", kwargs={"public_id": job_seeker.public_id})
        response = client.get(url)
        # Check that the page didn't crash
        assertNotContains(response, self.APPROVAL_NUMBER_LABEL)
        assertContains(response, "Informations du salarié")
        assertContains(response, "Candidatures de ce salarié")

    def test_multiple_approvals(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        expired_approval = ApprovalFactory(expired=True)
        JobApplicationFactory(
            approval=expired_approval,
            job_seeker=expired_approval.user,
            to_company=company,
            state=JobApplicationState.ACCEPTED,
        )
        new_approval = JobApplicationFactory(
            job_seeker=expired_approval.user, to_company=company, with_approval=True
        ).approval
        new_number = format_filters.format_approval_number(new_approval.number)
        expired_number = format_filters.format_approval_number(expired_approval.number)
        client.force_login(employer)
        url = reverse("employees:detail", kwargs={"public_id": new_approval.user.public_id})
        response = client.get(url)
        assertContains(response, new_number)
        assertNotContains(response, expired_number)

        # Allow to show previous approvals
        response = client.get(f"{url}?approval={expired_approval.pk}")
        assertNotContains(response, new_number)
        assertContains(response, expired_number)

        # Handle invalid values
        for invalid_value in [0, "not_a_number"]:
            response = client.get(f"{url}?approval={invalid_value}")
            assertContains(response, new_number)
            assertNotContains(response, expired_number)

    @override_settings(TALLY_URL="https://tally.so")
    def test_edit_user_info_button(self, client):
        approval = ApprovalFactory(with_jobapplication=True)
        job_application = approval.jobapplication_set.get()
        employer = job_application.to_company.members.first()
        client.force_login(employer)
        url = reverse("employees:detail", kwargs={"public_id": approval.user.public_id})

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

    @override_settings(TALLY_URL="https://tally.so")
    def test_link_immersion_facile(self, client, snapshot):
        today = timezone.localdate()
        approval = ApprovalFactory(
            with_jobapplication=True,
            start_at=(today - datetime.timedelta(days=90)),
            end_at=today,
        )
        job_application = approval.jobapplication_set.get()
        employer = job_application.to_company.members.first()
        url = reverse("employees:detail", kwargs={"public_id": approval.user.public_id})
        client.force_login(employer)

        response = client.get(url)
        assert response.context["link_immersion_facile"] == immersion_search_url(approval.user)
        alert = parse_response_to_soup(response, selector="#immersion-facile-opportunity-alert")
        assert pretty_indented(alert) == snapshot(name="alerte à l'opportunité immersion facile PASS expirant bientôt")

        approval.end_at = today - datetime.timedelta(days=1)
        approval.save()
        response = client.get(url)
        assert response.context["link_immersion_facile"] == immersion_search_url(approval.user)
        alert = parse_response_to_soup(response, selector="#immersion-facile-opportunity-alert")
        assert pretty_indented(alert) == snapshot(name="alerte à l'opportunité immersion facile PASS expiré")

        approval.end_at = today + datetime.timedelta(days=90)
        approval.save()
        response = client.get(url)
        assert response.context["link_immersion_facile"] == immersion_search_url(approval.user)
        alert = parse_response_to_soup(response, selector="#immersion-facile-opportunity-alert")
        assert pretty_indented(alert) == snapshot(
            name="alerte à l'opportunité immersion facile PASS expirant dans longtemps"
        )

        approval.start_at = today + datetime.timedelta(days=2)
        approval.end_at = today + datetime.timedelta(days=365)
        approval.save()
        response = client.get(url)
        assert response.context["link_immersion_facile"] == immersion_search_url(approval.user)
        alert = parse_response_to_soup(response, selector="#immersion-facile-opportunity-alert")
        assert pretty_indented(alert) == snapshot(name="alerte à l'opportunité immersion facile PASS non démarré")
