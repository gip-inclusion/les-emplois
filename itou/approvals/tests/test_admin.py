import pytest
from django.urls import reverse
from pytest_django.asserts import assertNotContains

from itou.approvals.factories import ApprovalFactory, ProlongationFactory, SuspensionFactory
from itou.job_applications.factories import JobApplicationFactory
from itou.users.factories import ItouStaffFactory
from itou.utils.test import parse_response_to_soup


class TestApprovalAdmin:
    def test_change_approval_with_jobapp_no_hiring_dates(self, client):
        approval = ApprovalFactory(with_jobapplication=True)
        approval.jobapplication_set.add(
            JobApplicationFactory(hiring_start_at=None, hiring_end_at=None, job_seeker=approval.user)
        )
        client.force_login(ItouStaffFactory(is_superuser=True))
        response = client.get(reverse("admin:approvals_approval_change", kwargs={"object_id": approval.pk}))
        assert response.status_code == 200


@pytest.mark.parametrize("field", ["start_at", "end_at"])
def test_approval_form_has_warnings_if_suspension_or_prolongation(admin_client, snapshot, field):
    approval = ApprovalFactory()
    response = admin_client.get(reverse("admin:approvals_approval_change", kwargs={"object_id": approval.pk}))
    assertNotContains(
        response,
        "En cas de modification, vérifier la cohérence avec " "les périodes de suspension et de prolongation.",
    )

    suspension = SuspensionFactory(approval=approval)
    response = admin_client.get(reverse("admin:approvals_approval_change", kwargs={"object_id": approval.pk}))
    field_helptext = parse_response_to_soup(response, selector=f"#id_{field}_helptext")
    assert str(field_helptext) == snapshot(name="obnoxious start_at and end_at warning")

    suspension.delete()
    ProlongationFactory(approval=approval)
    response = admin_client.get(reverse("admin:approvals_approval_change", kwargs={"object_id": approval.pk}))
    field_helptext = parse_response_to_soup(response, selector=f"#id_{field}_helptext")
    assert str(field_helptext) == snapshot(name="obnoxious start_at and end_at warning")
