from io import BytesIO

import pytest
from django.contrib import messages
from django.contrib.admin import helpers
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertMessages, assertNotContains

from itou.approvals.enums import ProlongationReason
from itou.files.models import File
from itou.job_applications.enums import JobApplicationState
from itou.utils.admin import get_admin_view_link
from tests.approvals.factories import ApprovalFactory, CancelledApprovalFactory, ProlongationFactory, SuspensionFactory
from tests.companies.factories import CompanyFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import ItouStaffFactory, JobSeekerFactory
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
    selector = f"#id_{field}_helptext"

    approval = ApprovalFactory()
    response = admin_client.get(reverse("admin:approvals_approval_change", kwargs={"object_id": approval.pk}))
    soup = parse_response_to_soup(response)
    assert soup.select(selector) == []

    suspension = SuspensionFactory(approval=approval)
    response = admin_client.get(reverse("admin:approvals_approval_change", kwargs={"object_id": approval.pk}))
    field_helptext = parse_response_to_soup(response, selector=selector)
    assert str(field_helptext) == snapshot(name="obnoxious start_at and end_at warning")

    suspension.delete()
    ProlongationFactory(approval=approval)
    response = admin_client.get(reverse("admin:approvals_approval_change", kwargs={"object_id": approval.pk}))
    field_helptext = parse_response_to_soup(response, selector=selector)
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


def test_filter_assigned_company(admin_client):
    company = CompanyFactory()
    job_seeker = JobSeekerFactory()
    JobApplicationFactory(to_company=company, job_seeker=job_seeker)
    approval = ApprovalFactory(user=job_seeker)
    JobApplicationFactory(
        approval=approval,
        to_company=company,
        job_seeker=job_seeker,
        state=JobApplicationState.ACCEPTED,
    )
    response = admin_client.get(reverse("admin:approvals_approval_changelist"), {"assigned_company": company.pk})
    assertContains(response, "1 PASS IAE")
    assertContains(
        response,
        f"""
        <th class="field-pk">
        <a href="/admin/approvals/approval/{approval.pk}/change/?_changelist_filters=assigned_company%3D{company.pk}">
        {approval.pk}
        </a>
        </th>
        """,
        html=True,
        count=1,
    )


def test_send_approvals_to_pe_stats(admin_client):
    ApprovalFactory(pe_notification_status="notification_error")
    CancelledApprovalFactory(pe_notification_status="notification_should_retry")

    approval_stats_url = reverse("admin:approvals_approval_sent_to_pe_stats")
    response = admin_client.get(reverse("admin:approvals_approval_changelist"))
    assertContains(response, approval_stats_url)
    response = admin_client.get(approval_stats_url)
    assertContains(response, "<h2>PASS IAE : 1</h2>")
    assertContains(response, "<h2>PASS IAE annulés : 1</h2>")

    cancelledapproval_stats_url = reverse("admin:approvals_cancelledapproval_sent_to_pe_stats")
    response = admin_client.get(reverse("admin:approvals_cancelledapproval_changelist"))
    assertContains(response, cancelledapproval_stats_url)
    response = admin_client.get(cancelledapproval_stats_url)
    assertContains(response, "<h2>PASS IAE : 1</h2>")
    assertContains(response, "<h2>PASS IAE annulés : 1</h2>")


def test_check_inconsistency_check(admin_client):
    consistent_approval = ApprovalFactory()

    response = admin_client.post(
        reverse("admin:approvals_approval_changelist"),
        {
            "action": "check_inconsistencies",
            helpers.ACTION_CHECKBOX_NAME: [consistent_approval.pk],
        },
        follow=True,
    )
    assertContains(response, "Aucune incohérence trouvée")

    inconsistent_approval = ApprovalFactory()
    inconsistent_approval.eligibility_diagnosis.job_seeker = JobSeekerFactory()
    inconsistent_approval.eligibility_diagnosis.save()

    response = admin_client.post(
        reverse("admin:approvals_approval_changelist"),
        {
            "action": "check_inconsistencies",
            helpers.ACTION_CHECKBOX_NAME: [consistent_approval.pk, inconsistent_approval.pk],
        },
        follow=True,
    )
    assertMessages(
        response,
        [
            messages.Message(
                messages.WARNING,
                (
                    '1 objet incohérent: <ul><li class="warning">'
                    f'<a href="/admin/approvals/approval/{inconsistent_approval.pk}/change/">'
                    f"PASS IAE - {inconsistent_approval.pk}"
                    "</a>: PASS IAE lié au diagnostic d&#x27;un autre candidat"
                    "</li></ul>"
                ),
            )
        ],
    )
