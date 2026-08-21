import datetime

from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertRedirects

from itou.approvals.utils import SUSPENSION_DURATION_BEFORE_APPROVAL_CLOSABLE
from itou.job_applications.enums import JobApplicationState
from tests.approvals.factories import ApprovalFactory, SuspensionFactory
from tests.companies.factories import CompanyMembershipFactory
from tests.job_applications.factories import JobApplicationFactory


def _closable_approval(to_company):
    """An approval whose suspension makes it eligible for closure by *to_company*."""
    approval = ApprovalFactory(
        with_jobapplication=True,
        with_jobapplication__to_company=to_company,
        start_at=timezone.localdate() - SUSPENSION_DURATION_BEFORE_APPROVAL_CLOSABLE - datetime.timedelta(days=3),
    )
    SuspensionFactory(approval=approval, long_enough_to_close=True, end_at=timezone.localdate())
    return approval


class TestCloseApprovalView:
    def test_close_approval(self, client, mailoutbox, caplog):
        membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
        approval = _closable_approval(membership.company)
        client.force_login(membership.user)

        back_url = reverse("dashboard:index")
        url = reverse("approvals:close", kwargs={"approval_id": approval.pk}, query={"back_url": back_url})
        response = client.post(url, data={"situation_reviewed": "on", "candidate_informed": "on"})

        assertRedirects(response, back_url)
        approval.refresh_from_db()
        assert approval.end_at == timezone.localdate() - datetime.timedelta(days=1)
        assert f"user={membership.user.pk} closed approval={approval.pk}" in caplog.messages

        [email] = mailoutbox
        assert email.to == [approval.user.email]
        assert "Clôture de votre PASS IAE" in email.subject

    def test_close_approval_missing_attestations(self, client):
        membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
        approval = _closable_approval(membership.company)
        client.force_login(membership.user)

        response = client.post(reverse("approvals:close", kwargs={"approval_id": approval.pk}))
        assert response.context["form"].errors == {
            "situation_reviewed": ["Ce champ est obligatoire."],
            "candidate_informed": ["Ce champ est obligatoire."],
        }
        approval.refresh_from_db()
        assert approval.end_at != timezone.localdate()

    def test_get(self, client):
        membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
        approval = _closable_approval(membership.company)
        client.force_login(membership.user)

        response = client.get(reverse("approvals:close", kwargs={"approval_id": approval.pk}))
        assert response.status_code == 200

    def test_not_closable_returns_403(self, client):
        membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
        approval = ApprovalFactory(with_jobapplication=True, with_jobapplication__to_company=membership.company)
        client.force_login(membership.user)

        response = client.post(reverse("approvals:close", kwargs={"approval_id": approval.pk}))
        assert response.status_code == 403

    def test_other_company_returns_404(self, client):
        approval = ApprovalFactory()
        other_user = CompanyMembershipFactory(company__subject_to_iae_rules=True).user
        client.force_login(other_user)

        response = client.post(reverse("approvals:close", kwargs={"approval_id": approval.pk}))
        assert response.status_code == 404

    def test_previous_employer_returns_404(self, client):
        previous = CompanyMembershipFactory(company__subject_to_iae_rules=True)
        approval = _closable_approval(previous.company)
        current = CompanyMembershipFactory(company__subject_to_iae_rules=True)
        JobApplicationFactory(
            sent_by_prescriber_alone=True,
            job_seeker=approval.user,
            approval=approval,
            to_company=current.company,
            state=JobApplicationState.ACCEPTED,
        )
        client.force_login(previous.user)

        response = client.post(reverse("approvals:close", kwargs={"approval_id": approval.pk}))
        assert response.status_code == 404
