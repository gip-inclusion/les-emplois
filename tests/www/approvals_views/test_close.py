import datetime

from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertRedirects

from itou.approvals.utils import SUSPENSION_DURATION_BEFORE_APPROVAL_CLOSABLE
from tests.approvals.factories import ApprovalFactory, SuspensionFactory
from tests.companies.factories import CompanyMembershipFactory


def _closable_approval(to_company):
    """An approval whose suspension makes it eligible for closure by *to_company*."""
    duration = SUSPENSION_DURATION_BEFORE_APPROVAL_CLOSABLE + datetime.timedelta(days=2)
    suspension_start_at = timezone.localdate() - duration
    approval = ApprovalFactory(
        with_jobapplication=True,
        with_jobapplication__to_company=to_company,
        start_at=suspension_start_at - datetime.timedelta(days=1),
    )
    SuspensionFactory(approval=approval, start_at=suspension_start_at, end_at=timezone.localdate())
    return approval


class TestCloseApprovalView:
    def test_close_approval(self, client, mailoutbox, caplog):
        membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
        approval = _closable_approval(membership.company)
        client.force_login(membership.user)

        back_url = reverse("dashboard:index")
        url = reverse("approvals:close", kwargs={"approval_id": approval.pk}, query={"back_url": back_url})
        response = client.post(url)

        assertRedirects(response, back_url)
        approval.refresh_from_db()
        assert approval.end_at == timezone.localdate()
        assert f"user={membership.user.pk} closed approval={approval.pk}" in caplog.messages

        [email] = mailoutbox
        assert email.to == [approval.user.email]
        assert "Clôture de votre PASS IAE" in email.subject

    def test_get_not_allowed(self, client):
        membership = CompanyMembershipFactory(company__subject_to_iae_rules=True)
        approval = _closable_approval(membership.company)
        client.force_login(membership.user)

        response = client.get(reverse("approvals:close", kwargs={"approval_id": approval.pk}))
        assert response.status_code == 405

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
