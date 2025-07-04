from datetime import UTC, datetime

import pytest
from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.contrib.admin import helpers
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertMessages, assertNotContains, assertRedirects

from itou.approvals.enums import Origin, ProlongationReason
from itou.approvals.models import Suspension
from itou.job_applications.enums import JobApplicationState
from itou.utils.admin import get_admin_view_link
from tests.approvals.factories import ApprovalFactory, CancelledApprovalFactory, ProlongationFactory, SuspensionFactory
from tests.companies.factories import CompanyFactory
from tests.files.factories import FileFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import ItouStaffFactory, JobSeekerFactory
from tests.utils.test import parse_response_to_soup, pretty_indented


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
    assert pretty_indented(field_helptext) == snapshot(name="obnoxious start_at and end_at warning")

    suspension.delete()
    ProlongationFactory(approval=approval)
    response = admin_client.get(reverse("admin:approvals_approval_change", kwargs={"object_id": approval.pk}))
    field_helptext = parse_response_to_soup(response, selector=selector)
    assert pretty_indented(field_helptext) == snapshot(name="obnoxious start_at and end_at warning")


def test_prolongation_report_file_filter(admin_client):
    prolongation = ProlongationFactory(report_file=FileFactory(), reason=ProlongationReason.SENIOR)

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
    assertContains(response, "1 PASS IAE")
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
    assertContains(response, "<h2>PASS IAE : 1</h2>")
    assertContains(response, "<h2>PASS IAE annulés : 1</h2>")

    cancelledapproval_stats_url = reverse("admin:approvals_cancelledapproval_sent_to_pe_stats")
    response = admin_client.get(reverse("admin:approvals_cancelledapproval_changelist"))
    assertContains(response, cancelledapproval_stats_url)
    response = admin_client.get(cancelledapproval_stats_url)
    assertContains(response, "<h2>PASS IAE : 1</h2>")
    assertContains(response, "<h2>PASS IAE annulés : 1</h2>")


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
                    f"PASS IAE - {inconsistent_approval.pk}"
                    "</a>: PASS IAE lié au diagnostic d&#x27;un autre candidat"
                    "</li></ul>"
                ),
            )
        ],
    )


@pytest.mark.parametrize(
    "origin,diag_required",
    [
        (Origin.ADMIN, True),
        (Origin.DEFAULT, True),
        (Origin.AI_STOCK, False),
        (Origin.PE_APPROVAL, False),
    ],
)
def test_approval_eligibility_diagnosis(admin_client, origin, diag_required):
    kwargs = {"origin": origin}
    if not diag_required:
        kwargs["eligibility_diagnosis"] = None
    approval = ApprovalFactory(**kwargs)
    post_data = {
        "start_at": str(approval.start_at),
        "initial-start_at": str(approval.start_at),
        "end_at": str(approval.end_at),
        "initial-end_at": str(approval.end_at),
        "user": str(approval.user.pk),
        "eligibility_diagnosis": "",
        "suspension_set-TOTAL_FORMS": "0",
        "suspension_set-INITIAL_FORMS": "0",
        "suspension_set-MIN_NUM_FORMS": "0",
        "suspension_set-MAX_NUM_FORMS": "0",
        "prolongation_set-TOTAL_FORMS": "0",
        "prolongation_set-INITIAL_FORMS": "0",
        "prolongation_set-MIN_NUM_FORMS": "0",
        "prolongation_set-MAX_NUM_FORMS": "0",
        "prolongationrequest_set-TOTAL_FORMS": "0",
        "prolongationrequest_set-INITIAL_FORMS": "0",
        "prolongationrequest_set-MIN_NUM_FORMS": "0",
        "prolongationrequest_set-MAX_NUM_FORMS": "0",
        "jobapplication_set-TOTAL_FORMS": "0",
        "jobapplication_set-INITIAL_FORMS": "0",
        "jobapplication_set-MIN_NUM_FORMS": "0",
        "jobapplication_set-MAX_NUM_FORMS": "0",
        "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": "1",
        "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": "0",
        "utils-pksupportremark-content_type-object_id-MIN_NUM_FORMS": "0",
        "utils-pksupportremark-content_type-object_id-MAX_NUM_FORMS": "1",
        "utils-pksupportremark-content_type-object_id-0-remark": "",
        "utils-pksupportremark-content_type-object_id-0-id": "",
        "utils-pksupportremark-content_type-object_id-__prefix__-remark": "",
        "utils-pksupportremark-content_type-object_id-__prefix__-id": "",
    }
    response = admin_client.post(
        reverse("admin:approvals_approval_change", kwargs={"object_id": approval.pk}),
        data=post_data,
    )
    if diag_required:
        assert response.status_code == 200
        assert response.context["errors"] == [["Ce champ est obligatoire"]]
    else:
        assertRedirects(response, reverse("admin:approvals_approval_changelist"))


def test_search_fields(admin_client):
    list_url = reverse("admin:approvals_approval_changelist")
    approval1 = ApprovalFactory(
        user__first_name="Jean Michel",
        user__last_name="Dupont",
        user__email="jean.michel@example.com",
        user__jobseeker_profile__nir="190031398700953",
        origin_pe_approval=True,
        number="123456789012",
    )
    url_1 = reverse("admin:approvals_approval_change", kwargs={"object_id": approval1.pk})
    approval2 = ApprovalFactory(
        user__first_name="Pierre François",
        user__last_name="Martin",
        user__email="pierre.francois@example.com",
        user__jobseeker_profile__nir="",
    )
    url_2 = reverse("admin:approvals_approval_change", kwargs={"object_id": approval2.pk})

    # Nothing to hide
    response = admin_client.get(list_url)
    assertContains(response, url_1)
    assertContains(response, url_2)

    # Search by approval number
    response = admin_client.get(list_url, {"q": approval2.number})
    assertNotContains(response, url_1)
    assertContains(response, url_2)

    # Search by partial number
    response = admin_client.get(list_url, {"q": approval1.number[1:-1]})
    assertContains(response, url_1)
    assertNotContains(response, url_2)

    # Search by NIR
    response = admin_client.get(list_url, {"q": approval1.user.jobseeker_profile.nir})
    assertContains(response, url_1)
    assertNotContains(response, url_2)

    # Search on email
    response = admin_client.get(list_url, {"q": "michel@example"})
    assertContains(response, url_1)
    assertNotContains(response, url_2)

    # Search on first_name
    response = admin_client.get(list_url, {"q": "françois"})
    assertNotContains(response, url_1)
    assertContains(response, url_2)

    # Search on last_name
    response = admin_client.get(list_url, {"q": "martin"})
    assertNotContains(response, url_1)
    assertContains(response, url_2)


@freeze_time("2025-06-20", tick=False)
def test_suspension_form(admin_client):
    initial_start_date = datetime(2025, 6, 1, tzinfo=UTC)
    initial_end_date = Suspension.get_max_end_at(initial_start_date)
    suspension = SuspensionFactory(
        start_at=initial_start_date.date(),
        end_at=initial_end_date.date(),
        approval__start_at=datetime(2025, 2, 1, tzinfo=UTC).date(),
        created_at=initial_start_date,
    )
    url = reverse("admin:approvals_suspension_change", args=(suspension.pk,))
    response = admin_client.get(url)
    assert response.status_code == 200

    basic_data = {
        "approval": suspension.approval.pk,
        "siae": suspension.siae.pk,
        "reason": suspension.reason,
        "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": "1",
        "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": 0,
        "utils-pksupportremark-content_type-object_id-MIN_NUM_FORMS": 0,
        "utils-pksupportremark-content_type-object_id-MAX_NUM_FORMS": 1,
        "utils-pksupportremark-content_type-object_id-0-remark": "",
        "utils-pksupportremark-content_type-object_id-0-id": "",
        "utils-pksupportremark-content_type-object_id-__prefix__-remark": "",
        "utils-pksupportremark-content_type-object_id-__prefix__-id": "",
    }

    # No retroactivity: new suspension.start at > suspension.created_at
    new_start_date = datetime(2025, 6, 20, tzinfo=UTC)
    new_end_date = Suspension.get_max_end_at(new_start_date)

    response = admin_client.post(
        url,
        data=basic_data
        | {
            "start_at": new_start_date.strftime("%d/%m/%Y"),
            "initial-start_at": initial_start_date.strftime("%d/%m/%Y"),
            "end_at": new_end_date.strftime("%d/%m/%Y"),
            "initial-end_at": initial_end_date.strftime("%d/%m/%Y"),
        },
    )
    assert response.status_code == 302
    suspension.refresh_from_db()
    assert suspension.start_at == new_start_date.date()
    assert suspension.end_at == new_end_date.date()

    # Retroactivity: new suspension start at < suspension.created_at.
    new_start_date = suspension.created_at - relativedelta(days=4)
    new_end_date = Suspension.get_max_end_at(new_start_date)
    response = admin_client.post(
        url,
        data=basic_data
        | {
            "start_at": new_start_date.strftime("%d/%m/%Y"),
            "initial-start_at": suspension.start_at.strftime("%d/%m/%Y"),
            "end_at": new_end_date.strftime("%d/%m/%Y"),
            "initial-end_at": suspension.end_at.strftime("%d/%m/%Y"),
        },
    )
    assert response.status_code == 302
    suspension.refresh_from_db()
    assert suspension.start_at == new_start_date.date()
    assert suspension.end_at == new_end_date.date()
    assert suspension.updated_at == timezone.now()
