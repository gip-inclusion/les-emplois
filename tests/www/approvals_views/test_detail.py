from django.urls import reverse
from pytest_django.asserts import assertRedirects

from tests.approvals.factories import (
    ApprovalFactory,
)
from tests.companies.factories import CompanyMembershipFactory


class RedirectToEmployeeView:
    def test_anonymous_user(self, client):
        approval = ApprovalFactory()
        url = reverse("approvals:redirect_to_employee", kwargs={"pk": approval.pk})
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_redirect(self, client):
        membership = CompanyMembershipFactory()
        client.force_login(membership.user)
        approval = ApprovalFactory()
        response = client.get(reverse("approvals:redirect_to_employee", kwargs={"pk": approval.pk}))
        assertRedirects(response, reverse("employees:detail", kwargs={"public_id": approval.user.public_id}))
