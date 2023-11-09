from io import BytesIO

import pytest
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertNotContains

from itou.approvals.enums import ProlongationReason
from itou.files.models import File
from itou.utils.admin import get_admin_view_link
from tests.approvals.factories import ApprovalFactory, ProlongationFactory, SuspensionFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import ItouStaffFactory
from tests.utils.test import parse_response_to_soup


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


def test_prolongation_report_file_filter(admin_client):
    with BytesIO(b"foo") as file:
        report_file = File(file, last_modified=timezone.now())
        report_file.save()
    prolongation = ProlongationFactory(report_file=report_file, reason=ProlongationReason.SENIOR)

    response = admin_client.get(reverse("admin:approvals_prolongation_changelist"), follow=True)
    assertContains(response, prolongation.approval.number)
    assertContains(response, prolongation.declared_by)

    response = admin_client.get(reverse("admin:approvals_prolongation_changelist") + "?report_file=yes", follow=True)
    assertContains(response, prolongation.approval.number)
    assertContains(response, prolongation.declared_by)

    response = admin_client.get(reverse("admin:approvals_prolongation_changelist") + "?report_file=no", follow=True)
    assertNotContains(response, prolongation.approval.number)
    assertNotContains(response, prolongation.declared_by)


def test_create_suspensionç_with_no_approval_does_raise_500(admin_client):
    response = admin_client.post(
        reverse("admin:approvals_suspension_add"),
        data={},
    )
    assert response.status_code == 200


def test_assigned_company(admin_client):
    approval = ApprovalFactory(with_jobapplication=True)
    siae = approval.jobapplication_set.get().to_company
    response = admin_client.get(reverse("admin:approvals_approval_change", kwargs={"object_id": approval.pk}))
    assertContains(response, get_admin_view_link(siae, content=siae.display_name), count=2)
