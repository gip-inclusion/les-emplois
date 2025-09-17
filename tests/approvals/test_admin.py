import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.contrib.admin import AdminSite, helpers
from django.contrib.auth import get_user
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.forms import model_to_dict
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import (
    assertContains,
    assertMessages,
    assertNotContains,
    assertRedirects,
)

from itou.approvals.admin import JobApplicationInline
from itou.approvals.admin_forms import ApprovalAdminForm
from itou.approvals.enums import Origin, ProlongationReason
from itou.approvals.models import Approval, Prolongation, Suspension
from itou.companies.enums import CompanyKind
from itou.employee_record.enums import Status
from itou.job_applications.enums import JobApplicationState, SenderKind
from itou.job_applications.models import JobApplication
from itou.users.enums import LackOfPoleEmploiId
from itou.users.models import User
from itou.utils.admin import get_admin_view_link
from itou.utils.models import PkSupportRemark
from tests.approvals.factories import (
    ApprovalFactory,
    CancelledApprovalFactory,
    ProlongationFactory,
    SuspensionFactory,
)
from tests.companies.factories import CompanyFactory
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.employee_record.factories import EmployeeRecordFactory
from tests.files.factories import FileFactory
from tests.job_applications.factories import JobApplicationFactory, JobApplicationSentByJobSeekerFactory
from tests.users.factories import ItouStaffFactory, JobSeekerFactory
from tests.utils.testing import parse_response_to_soup, pretty_indented


class TestApprovalAdmin:
    def test_change_approval_with_jobapp_no_hiring_dates(self, client):
        approval = ApprovalFactory(with_jobapplication=True)
        approval.jobapplication_set.add(
            JobApplicationFactory(hiring_start_at=None, hiring_end_at=None, job_seeker=approval.user)
        )
        client.force_login(ItouStaffFactory(is_superuser=True))
        response = client.get(reverse("admin:approvals_approval_change", kwargs={"object_id": approval.pk}))
        assert response.status_code == 200

    def test_approval_form_has_warnings_if_suspension_or_prolongation(self, admin_client, snapshot):
        selector = "#id_start_at_helptext"

        approval = ApprovalFactory()
        response = admin_client.get(reverse("admin:approvals_approval_change", kwargs={"object_id": approval.pk}))
        soup = parse_response_to_soup(response)
        assert soup.select(selector) == []

        suspension = SuspensionFactory(approval=approval)
        response = admin_client.get(reverse("admin:approvals_approval_change", kwargs={"object_id": approval.pk}))
        field_helptext = parse_response_to_soup(response, selector=selector)
        assert pretty_indented(field_helptext) == snapshot(name="obnoxious start_at warning")

        suspension.delete()
        ProlongationFactory(approval=approval)
        response = admin_client.get(reverse("admin:approvals_approval_change", kwargs={"object_id": approval.pk}))
        field_helptext = parse_response_to_soup(response, selector=selector)
        assert pretty_indented(field_helptext) == snapshot(name="obnoxious start_at warning")

    def test_assigned_company(self, admin_client):
        approval = ApprovalFactory(with_jobapplication=True)
        siae = approval.jobapplication_set.get().to_company
        response = admin_client.get(reverse("admin:approvals_approval_change", kwargs={"object_id": approval.pk}))
        assertContains(response, get_admin_view_link(siae, content=siae.display_name), count=2)

    def test_filter_assigned_company(self, admin_client):
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
        expected_url = (
            reverse("admin:approvals_approval_change", args=(approval.pk,))
            + f"?_changelist_filters=assigned_company%3D{company.pk}"
        )
        assertContains(
            response,
            f"""
            <th class="field-pk">
            <a href="{expected_url}">
            {approval.pk}
            </a>
            </th>
            """,
            html=True,
            count=1,
        )

    def test_send_approvals_to_pe_stats(self, admin_client):
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

    def test_check_inconsistency_check(self, admin_client):
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
    def test_approval_eligibility_diagnosis(self, admin_client, origin, diag_required):
        kwargs = {"origin": origin}
        if not diag_required:
            kwargs["eligibility_diagnosis"] = None
        approval = ApprovalFactory(**kwargs)
        post_data = {
            "start_at": str(approval.start_at),
            "initial-start_at": str(approval.start_at),
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

    def test_search_fields(self, admin_client):
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

    def test_change_approval_user_display_with_pii(self, client):
        approval = ApprovalFactory()
        client.force_login(ItouStaffFactory(is_superuser=True))
        response = client.get(reverse("admin:approvals_approval_change", kwargs={"object_id": approval.pk}))
        assertContains(response, approval.user.display_with_pii)

    def test_created_by_display(self, admin_client):
        staff_user = ItouStaffFactory()
        approval = ApprovalFactory(created_by=staff_user)
        response = admin_client.get(reverse("admin:approvals_approval_change", kwargs={"object_id": approval.pk}))
        assertContains(response, staff_user.display_with_pii)

    def test_terminate_approval_without_permission(self, client):
        user = ItouStaffFactory()
        start_at = timezone.localdate() - timedelta(days=10)
        approval = ApprovalFactory(start_at=start_at)
        end_at = approval.end_at
        client.force_login(user)
        response = client.post(reverse("admin:approvals_approval_terminate_approval", args=(approval.pk,)))
        assert response.status_code == 403
        approval.refresh_from_db()
        assert approval.start_at == start_at
        assert approval.end_at == end_at

    def test_terminate_expired_approval(self, admin_client):
        approval = ApprovalFactory(expired=True)
        response = admin_client.post(reverse("admin:approvals_approval_terminate_approval", args=(approval.pk,)))
        assert response.status_code == 404

    @freeze_time("2025-08-21")
    def test_terminate_approval(self, admin_client, caplog):
        start_at = timezone.localdate() - timedelta(days=10)
        approval = ApprovalFactory(start_at=start_at)
        original_end_at = approval.end_at
        today = timezone.localdate()
        response = admin_client.post(reverse("admin:approvals_approval_terminate_approval", args=(approval.pk,)))
        assertRedirects(response, reverse("admin:approvals_approval_change", args=(approval.pk,)))
        approval.refresh_from_db()
        assert approval.start_at == start_at
        assert approval.end_at == today
        assert f"Terminating approval pk={approval.pk}, end_at={today} (was {original_end_at})." in caplog.messages
        approval_content_type = ContentType.objects.get_for_model(Approval)
        support_remark = PkSupportRemark.objects.filter(
            content_type=approval_content_type,
            object_id=approval.pk,
        ).get()
        user = User.objects.get(pk=get_user(admin_client).pk)
        assert support_remark.remark == f"2025-08-21 : PASS IAE clôturé par {user.get_full_name()}."

    @freeze_time()
    def test_terminate_approval_with_future_suspension_and_prolongation(self, admin_client, caplog):
        start_at = timezone.localdate() - timedelta(days=100)
        end_at = timezone.localdate() + timedelta(days=10)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        today = timezone.localdate()
        suspension_end = today + timedelta(days=10)
        suspension = SuspensionFactory(approval=approval, start_at=today, end_at=suspension_end)
        approval.refresh_from_db()
        prolongation = ProlongationFactory(
            approval=approval, start_at=approval.end_at, end_at=approval.end_at + timedelta(days=10)
        )
        approval.refresh_from_db()
        original_end_at = approval.end_at

        response = admin_client.post(reverse("admin:approvals_approval_terminate_approval", args=(approval.pk,)))
        assertRedirects(response, reverse("admin:approvals_approval_change", args=(approval.pk,)))
        approval.refresh_from_db()
        assert approval.start_at == start_at
        assert approval.end_at == today
        with pytest.raises(Prolongation.DoesNotExist):
            prolongation.refresh_from_db()
        with pytest.raises(Suspension.DoesNotExist):
            suspension.refresh_from_db()
        assert f"Terminating approval pk={approval.pk}, deleting 1 future approvals.Prolongation." in caplog.messages
        assert f"Terminating approval pk={approval.pk}, deleting 1 future approvals.Suspension." in caplog.messages
        assert f"Terminating approval pk={approval.pk}, end_at={today} (was {original_end_at})." in caplog.messages

    @freeze_time()
    def test_terminate_approval_with_ongoing_suspension(self, admin_client, caplog):
        start_at = timezone.localdate() - timedelta(days=100)
        end_at = timezone.localdate() + timedelta(days=10)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        today = timezone.localdate()
        suspension_start = today - timedelta(days=10)
        suspension_end = today + timedelta(days=10)
        suspension = SuspensionFactory(approval=approval, start_at=suspension_start, end_at=suspension_end)
        approval.refresh_from_db()
        original_end_at = approval.end_at
        original_suspension_end_at = suspension.end_at

        response = admin_client.post(reverse("admin:approvals_approval_terminate_approval", args=(approval.pk,)))
        assertRedirects(response, reverse("admin:approvals_approval_change", args=(approval.pk,)))
        approval.refresh_from_db()
        assert approval.start_at == start_at
        assert approval.end_at == today
        suspension.refresh_from_db()
        assert suspension.start_at == suspension_start
        assert suspension.end_at == today
        assert (
            f"Terminating approval pk={approval.pk}, "
            f"setting approvals.Suspension pk={suspension.pk} end_at={today} (was {original_suspension_end_at})."
            in caplog.messages
        )
        assert f"Terminating approval pk={approval.pk}, end_at={today} (was {original_end_at})." in caplog.messages

    @freeze_time()
    def test_terminate_approval_with_ongoing_prolongation(self, admin_client, caplog):
        start_at = timezone.localdate() - timedelta(days=100)
        end_at = timezone.localdate() - timedelta(days=10)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        today = timezone.localdate()
        prolongation_start = approval.end_at
        prolongation_end = today + timedelta(days=10)
        prolongation = ProlongationFactory(approval=approval, start_at=prolongation_start, end_at=prolongation_end)
        approval.refresh_from_db()
        original_end_at = approval.end_at
        original_prolongation_end_at = prolongation.end_at

        response = admin_client.post(reverse("admin:approvals_approval_terminate_approval", args=(approval.pk,)))
        assertRedirects(response, reverse("admin:approvals_approval_change", args=(approval.pk,)))
        approval.refresh_from_db()
        assert approval.start_at == start_at
        assert approval.end_at == today
        prolongation.refresh_from_db()
        assert prolongation.start_at == prolongation_start
        assert prolongation.end_at == today
        assert (
            f"Terminating approval pk={approval.pk}, "
            f"setting approvals.Prolongation pk={prolongation.pk} end_at={today} (was {original_prolongation_end_at})."
            in caplog.messages
        )
        assert f"Terminating approval pk={approval.pk}, end_at={today} (was {original_end_at})." in caplog.messages

    @freeze_time()
    def test_terminate_approval_with_ongoing_suspension_during_prolongation(self, admin_client):
        start_at = timezone.localdate() - timedelta(days=100)
        end_at = timezone.localdate() - timedelta(days=10)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        today = timezone.localdate()
        prolongation_start = approval.end_at
        prolongation_end = today + timedelta(days=10)
        prolongation = ProlongationFactory(approval=approval, start_at=prolongation_start, end_at=prolongation_end)
        suspension_start = today - timedelta(days=3)
        suspension_end = today + timedelta(days=10)
        suspension = SuspensionFactory(approval=approval, start_at=suspension_start, end_at=suspension_end)

        response = admin_client.post(reverse("admin:approvals_approval_terminate_approval", args=(approval.pk,)))
        assertRedirects(response, reverse("admin:approvals_approval_change", args=(approval.pk,)))
        approval.refresh_from_db()
        assert approval.start_at == start_at
        assert approval.end_at == today
        prolongation.refresh_from_db()
        assert prolongation.start_at == prolongation_start
        assert prolongation.end_at == today
        suspension.refresh_from_db()
        assert suspension.start_at == suspension_start
        assert suspension.end_at == today

    @freeze_time()
    def test_terminate_approval_with_past_suspension(self, admin_client):
        start_at = timezone.localdate() - timedelta(days=100)
        end_at = timezone.localdate() - timedelta(days=10)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        today = timezone.localdate()
        suspension_start = today - timedelta(days=30)
        suspension_end = today - timedelta(days=10)
        suspension = SuspensionFactory(approval=approval, start_at=suspension_start, end_at=suspension_end)

        response = admin_client.post(reverse("admin:approvals_approval_terminate_approval", args=(approval.pk,)))
        assertRedirects(response, reverse("admin:approvals_approval_change", args=(approval.pk,)))
        approval.refresh_from_db()
        assert approval.start_at == start_at
        assert approval.end_at == today
        suspension.refresh_from_db()
        assert suspension.start_at == suspension_start
        assert suspension.end_at == suspension_end

    @freeze_time()
    def test_terminate_approval_with_past_prolongations(self, admin_client):
        start_at = timezone.localdate() - timedelta(days=100)
        end_at = timezone.localdate() - timedelta(days=10)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        today = timezone.localdate()
        past_prolongation_start = approval.end_at
        past_prolongation_end = today - timedelta(days=5)
        past_prolongation = ProlongationFactory(
            approval=approval, start_at=past_prolongation_start, end_at=past_prolongation_end
        )
        prolongation_start = past_prolongation_end
        prolongation_end = today + timedelta(days=5)
        prolongation = ProlongationFactory(approval=approval, start_at=prolongation_start, end_at=prolongation_end)

        response = admin_client.post(reverse("admin:approvals_approval_terminate_approval", args=(approval.pk,)))
        assertRedirects(response, reverse("admin:approvals_approval_change", args=(approval.pk,)))
        approval.refresh_from_db()
        assert approval.start_at == start_at
        assert approval.end_at == today
        past_prolongation.refresh_from_db()
        assert past_prolongation.start_at == past_prolongation_start
        assert past_prolongation.end_at == past_prolongation_end
        prolongation.refresh_from_db()
        assert prolongation.start_at == prolongation_start
        assert prolongation.end_at == today

    @pytest.mark.parametrize(
        "get_start_date,has_log",
        [
            pytest.param(timezone.localdate, False, id="start_date_not_changed"),
            pytest.param(lambda: timezone.localdate() - timedelta(days=100), True, id="start_date_changed"),
        ],
    )
    def test_change_start_date(self, admin_client, caplog, get_start_date, has_log):
        start_date = get_start_date()
        approval = ApprovalFactory(start_at=start_date)
        today = timezone.localdate()

        change_url = reverse("admin:approvals_approval_change", args=(approval.pk,))
        data = {
            "start_at": str(today),
            "initial-start_at": str(approval.start_at),
            "user": str(approval.user.pk),
            "eligibility_diagnosis": str(approval.eligibility_diagnosis_id),
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
            "_continue": "Enregistrer et continuer les modifications",
        }
        response = admin_client.post(change_url, data)
        assertRedirects(response, change_url)
        msg = f"Updating approval pk={approval.pk} start_at={today} (was {approval.start_at})."
        if has_log:
            assert msg in caplog.messages
        else:
            assert msg not in caplog.messages

    def test_change_start_date_prolongation(self, admin_client):
        start_at = timezone.localdate() - timedelta(days=100)
        end_at = timezone.localdate() - timedelta(days=10)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        today = timezone.localdate()
        prolongation_start = approval.end_at
        prolongation_end = today + timedelta(days=5)
        ProlongationFactory(approval=approval, start_at=prolongation_start, end_at=prolongation_end)
        approval.refresh_from_db()
        approval_duration = approval.end_at - approval.start_at

        change_url = reverse("admin:approvals_approval_change", args=(approval.pk,))
        data = {
            "start_at": str(prolongation_start),
            "user": str(approval.user.pk),
            "eligibility_diagnosis": str(approval.eligibility_diagnosis_id),
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
            "_continue": "Enregistrer et continuer les modifications",
        }
        response = admin_client.post(change_url, data)
        assertRedirects(response, change_url)
        approval.refresh_from_db()
        assert approval.start_at == prolongation_start
        assert approval.end_at == prolongation_start + approval_duration

        data["start_at"] = str(prolongation_start + timedelta(days=1))
        response = admin_client.post(change_url, data)
        assertContains(
            response,
            """
            <ul class="errorlist" id="id_start_at_error">
                <li>Cette date ne peut pas être après le début d’une prolongation ou d’une suspension.</li>
            </ul>
            """,
            html=True,
            count=1,
        )
        approval.refresh_from_db()
        assert approval.start_at == prolongation_start
        assert approval.end_at == prolongation_start + approval_duration

    def test_change_start_date_suspension(self, admin_client):
        start_at = timezone.localdate() - timedelta(days=100)
        approval = ApprovalFactory(start_at=start_at)
        today = timezone.localdate()
        suspension_start = today
        suspension_end = today + timedelta(days=10)
        SuspensionFactory(approval=approval, start_at=suspension_start, end_at=suspension_end)
        approval.refresh_from_db()
        approval_duration = approval.end_at - approval.start_at

        change_url = reverse("admin:approvals_approval_change", args=(approval.pk,))
        data = {
            "start_at": str(suspension_start),
            "user": str(approval.user.pk),
            "eligibility_diagnosis": str(approval.eligibility_diagnosis_id),
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
            "_continue": "Enregistrer et continuer les modifications",
        }
        response = admin_client.post(change_url, data)
        assertRedirects(response, change_url)
        approval.refresh_from_db()
        assert approval.start_at == suspension_start
        assert approval.end_at == suspension_start + approval_duration

        data["start_at"] = str(suspension_start + timedelta(days=1))
        response = admin_client.post(change_url, data)
        assertContains(
            response,
            """
            <ul class="errorlist" id="id_start_at_error">
                <li>Cette date ne peut pas être après le début d’une prolongation ou d’une suspension.</li>
            </ul>
            """,
            html=True,
            count=1,
        )
        approval.refresh_from_db()
        assert approval.start_at == suspension_start
        assert approval.end_at == suspension_start + approval_duration


def test_prolongation_report_file_filter(admin_client):
    prolongation = ProlongationFactory(report_file=FileFactory(), reason=ProlongationReason.SENIOR)

    response = admin_client.get(reverse("admin:approvals_prolongation_changelist"), follow=True)
    assertContains(response, prolongation.approval.number)
    assertContains(response, prolongation.declared_by.display_with_pii)

    response = admin_client.get(reverse("admin:approvals_prolongation_changelist") + "?report_file=yes", follow=True)
    assertContains(response, prolongation.approval.number)
    assertContains(response, prolongation.declared_by.display_with_pii)

    response = admin_client.get(reverse("admin:approvals_prolongation_changelist") + "?report_file=no", follow=True)
    assertNotContains(response, prolongation.approval.number)
    assertNotContains(response, prolongation.declared_by.display_with_pii)


def test_create_suspensionç_with_no_approval_does_raise_500(admin_client):
    response = admin_client.post(
        reverse("admin:approvals_suspension_add"),
        data={},
    )
    assert response.status_code == 200


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


class TestAutomaticApprovalAdminViews:
    def test_create_is_forbidden(self, client):
        """
        We cannot create an approval starting with ASP_ITOu_PREFIX
        """
        user = ItouStaffFactory()
        content_type = ContentType.objects.get_for_model(Approval)
        permission = Permission.objects.get(content_type=content_type, codename="add_approval")
        user.user_permissions.add(permission)

        client.force_login(user)

        url = reverse("admin:approvals_approval_add")

        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True)
        post_data = {
            "start_at": "01/01/2100",
            "end_at": "31/12/2102",
            "user": diagnosis.job_seeker_id,
            "eligibility_diagnosis": diagnosis.pk,
            "origin": Origin.DEFAULT,  # Will be overriden
            "number": "XXXXX1234567",
        }
        response = client.post(url, data=post_data)
        assert response.status_code == 403

    def test_edit_approval_with_an_existing_employee_record(self, client):
        user = ItouStaffFactory()
        user.user_permissions.add(
            Permission.objects.get(
                content_type=ContentType.objects.get_for_model(Approval),
                codename="change_approval",
            )
        )
        client.force_login(user)

        approval = ApprovalFactory()
        employee_record = EmployeeRecordFactory(approval_number=approval.number, status=Status.PROCESSED)

        response = client.post(
            reverse("admin:approvals_approval_change", args=[approval.pk]),
            data=model_to_dict(
                approval,
                fields={
                    "start_at",
                    "end_at",
                    "user",
                    "number",
                    "origin",
                    "eligibility_diagnosis",
                },
            ),
            follow=True,
        )
        assert response.status_code == 200
        assert (
            f"Il existe une ou plusieurs fiches salarié bloquantes "
            f'(<a href="/admin/employee_record/employeerecord/{employee_record.pk}/change/">{employee_record.pk}</a>) '
            f"pour la modification de ce PASS IAE ({approval.number})." == str(list(response.context["messages"])[0])
        )


class TestCustomApprovalAdminViews:
    def test_manually_add_approval(self, client, mailoutbox):
        MANUALLY_DELIVER_BUTTON_TEXT = "Enregistrer et envoyer par email"

        # When a Pôle emploi ID has been forgotten and the user has no NIR, an approval must be delivered
        # with a manual verification.
        job_seeker = JobSeekerFactory(
            jobseeker_profile__nir="",
            jobseeker_profile__pole_emploi_id="",
            jobseeker_profile__lack_of_pole_emploi_id_reason=LackOfPoleEmploiId.REASON_FORGOTTEN,
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker,
            state=JobApplicationState.PROCESSING,
            approval=None,
            approval_number_sent_by_email=False,
            with_iae_eligibility_diagnosis=True,
        )
        job_application.accept(user=job_application.to_company.members.first())

        url = reverse("admin:approvals_approval_manually_add_approval", args=[job_application.pk])

        # Not enough perms.
        user = JobSeekerFactory()
        client.force_login(user)
        response = client.get(url)
        assert response.status_code == 302

        # With good perms.
        user = ItouStaffFactory()
        client.force_login(user)
        content_type = ContentType.objects.get_for_model(Approval)
        permission = Permission.objects.get(content_type=content_type, codename="handle_manual_approval_requests")
        user.user_permissions.add(permission)
        response = client.get(url)
        assert response.status_code == 200
        assert response.context["form"].initial == {
            "start_at": job_application.hiring_start_at,
            "end_at": Approval.get_default_end_date(job_application.hiring_start_at),
        }
        assertContains(response, MANUALLY_DELIVER_BUTTON_TEXT)

        # Without an eligibility diangosis on the job application.
        eligibility_diagnosis = job_application.eligibility_diagnosis
        job_application.eligibility_diagnosis = None
        job_application.save()
        response = client.get(url, follow=True)
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Impossible de créer un PASS IAE car la candidature n'a pas de diagnostic d'éligibilité.",
                )
            ],
        )

        # Put back the eligibility diangosis
        job_application.eligibility_diagnosis = eligibility_diagnosis
        job_application.save()

        # With a valid approval the form is disabled
        other_job_application = JobApplicationFactory(job_seeker=job_seeker, with_approval=True)
        response = client.get(url, follow=True)
        assertNotContains(response, MANUALLY_DELIVER_BUTTON_TEXT)
        post_data = {
            "start_at": job_application.hiring_start_at.strftime("%d/%m/%Y"),
            "end_at": job_application.hiring_end_at.strftime("%d/%m/%Y"),
        }
        response = client.post(url, data=post_data)
        assert response.status_code == 403

        # Remove the valid approval
        other_job_application.approval.delete()

        # Les numéros avec le préfixe `ASP_ITOU_PREFIX` ne doivent pas pouvoir
        # être délivrés à la main dans l'admin.
        post_data = {
            "start_at": job_application.hiring_start_at.strftime("%d/%m/%Y"),
            "end_at": job_application.hiring_end_at.strftime("%d/%m/%Y"),
            "number": f"{Approval.ASP_ITOU_PREFIX}1234567",
        }
        response = client.post(url, data=post_data)
        assert response.status_code == 200
        assert "number" in response.context["form"].errors, ApprovalAdminForm.ERROR_NUMBER

        # Create an approval.
        post_data = {
            "start_at": job_application.hiring_start_at.strftime("%d/%m/%Y"),
            "end_at": job_application.hiring_end_at.strftime("%d/%m/%Y"),
        }
        response = client.post(url, data=post_data)
        assert response.status_code == 302

        # An approval should have been created, attached to the job
        # application, and sent by email.
        job_application = JobApplication.objects.get(pk=job_application.pk)
        assert job_application.approval_number_sent_by_email
        assert job_application.approval_number_sent_at is not None
        assert job_application.approval_manually_delivered_by == user
        assert job_application.approval_delivery_mode == job_application.APPROVAL_DELIVERY_MODE_MANUAL

        approval = job_application.approval
        assert approval.created_by == user
        assert approval.user == job_application.job_seeker
        assert approval.origin == Origin.ADMIN
        assert approval.eligibility_diagnosis == job_application.eligibility_diagnosis

        assert approval.origin_sender_kind == SenderKind.JOB_SEEKER
        assert approval.origin_siae_kind == job_application.to_company.kind
        assert approval.origin_siae_siret == job_application.to_company.siret
        assert not approval.origin_prescriber_organization_kind

        assert len(mailoutbox) == 1
        email = mailoutbox[0]
        assert approval.number_with_spaces in email.body

    def test_manually_refuse_approval(self, client, mailoutbox, snapshot):
        # When a Pôle emploi ID has been forgotten and the user has no NIR, an approval must be delivered
        # with a manual verification.
        job_seeker = JobSeekerFactory(
            first_name="Jean",
            last_name="Dupont",
            jobseeker_profile__nir="",
            jobseeker_profile__pole_emploi_id="",
            jobseeker_profile__lack_of_pole_emploi_id_reason=LackOfPoleEmploiId.REASON_FORGOTTEN,
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            pk=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            job_seeker=job_seeker,
            state=JobApplicationState.PROCESSING,
            approval=None,
            approval_number_sent_by_email=False,
            with_iae_eligibility_diagnosis=True,
        )
        employer = job_application.to_company.members.first()
        job_application.accept(user=employer)

        add_url = reverse("admin:approvals_approval_manually_add_approval", args=[job_application.pk])
        refuse_url = reverse("admin:approvals_approval_manually_refuse_approval", args=[job_application.pk])
        post_data = {"confirm": "yes"}

        # Not enough perms.
        user = ItouStaffFactory()
        client.force_login(user)
        response = client.post(refuse_url, data=post_data)
        assert response.status_code == 403

        # Set good perms.
        client.force_login(user)
        content_type = ContentType.objects.get_for_model(Approval)
        permission = Permission.objects.get(content_type=content_type, codename="handle_manual_approval_requests")
        user.user_permissions.add(permission)

        # With a valid approval
        other_job_application = JobApplicationFactory(job_seeker=job_seeker, with_approval=True)
        response = client.post(refuse_url, data=post_data)
        assert response.status_code == 403
        other_job_application.approval.delete()  # Remove the valid approval

        # Nominal case
        response = client.get(add_url)
        assertContains(response, refuse_url)

        response = client.get(refuse_url)
        assertContains(response, "PASS IAE refusé pour")

        post_data = {"confirm": "yes"}
        response = client.post(refuse_url, data=post_data)
        assert response.status_code == 302

        job_application = JobApplication.objects.get(pk=job_application.pk)
        assert job_application.approval_manually_refused_by == user
        assert job_application.approval_manually_refused_at is not None
        assert job_application.approval is None

        [email] = mailoutbox
        assert email.to == [employer.email]
        assert email.subject == snapshot(name="email_subject")
        assert email.body == snapshot(name="email_body")

    def test_employee_record_status(self, subtests):
        inline = JobApplicationInline(JobApplication, AdminSite())
        # When an employee record exists
        employee_record = EmployeeRecordFactory()
        url = reverse("admin:employee_record_employeerecord_change", args=[employee_record.id])
        msg = inline.employee_record_status(employee_record.job_application)
        assert msg == f'<a href="{url}"><b>Nouvelle (ID: {employee_record.pk})</b></a>'

        # When employee record creation is disabled for that job application
        job_application = JobApplicationFactory(create_employee_record=False)
        msg = inline.employee_record_status(job_application)
        assert msg == "Non proposé à la création"

        # When hiring start date is before employee record availability date
        job_application = JobApplicationFactory(hiring_start_at=date(2021, 9, 26))
        msg = inline.employee_record_status(job_application)
        assert msg == "Date de début du contrat avant l'interopérabilité"

        # When employee records are allowed (or not) for the SIAE
        for kind in CompanyKind:
            with subtests.test("SIAE doesn't use employee records", kind=kind.name):
                job_application = JobApplicationFactory(with_approval=True, to_company__kind=kind)
                msg = inline.employee_record_status(job_application)
                if not job_application.to_company.can_use_employee_record:
                    assert msg == "La SIAE ne peut pas utiliser la gestion des fiches salarié"
                else:
                    assert msg == "En attente de création"

        # When an employee record already exists for the candidate
        employee_record = EmployeeRecordFactory(status=Status.READY)
        job_application = JobApplicationFactory(
            to_company=employee_record.job_application.to_company,
            approval=employee_record.job_application.approval,
        )
        msg = inline.employee_record_status(job_application)
        assert msg == "Une fiche salarié existe déjà pour ce candidat"


def test_prolongation_inconsistency_check(admin_client):
    consistent_prolongation = ProlongationFactory()

    response = admin_client.post(
        reverse("admin:approvals_prolongation_changelist"),
        {
            "action": "check_inconsistencies",
            helpers.ACTION_CHECKBOX_NAME: [consistent_prolongation.pk],
        },
        follow=True,
    )
    assertContains(response, "Aucune incohérence trouvée")

    inconsistent_prolongation_1 = ProlongationFactory(
        approval__start_at=timezone.localdate(), start_at=timezone.localdate() - timedelta(days=1)
    )
    inconsistent_prolongation_2 = ProlongationFactory()
    inconsistent_prolongation_2.approval.end_at = inconsistent_prolongation_2.end_at - timedelta(days=1)
    inconsistent_prolongation_2.approval.save()

    response = admin_client.post(
        reverse("admin:approvals_prolongation_changelist"),
        {
            "action": "check_inconsistencies",
            helpers.ACTION_CHECKBOX_NAME: [
                consistent_prolongation.pk,
                inconsistent_prolongation_1.pk,
                inconsistent_prolongation_2.pk,
            ],
        },
        follow=True,
    )
    assertMessages(
        response,
        [
            messages.Message(
                messages.WARNING,
                (
                    '2 objets incohérents: <ul><li class="warning">'
                    f'<a href="/admin/approvals/prolongation/{inconsistent_prolongation_2.pk}/change/">'
                    f"prolongation - {inconsistent_prolongation_2.pk}"
                    "</a>: Prolongation hors période du PASS IAE"
                    '</li><li class="warning">'
                    f'<a href="/admin/approvals/prolongation/{inconsistent_prolongation_1.pk}/change/">'
                    f"prolongation - {inconsistent_prolongation_1.pk}"
                    "</a>: Prolongation hors période du PASS IAE"
                    "</li></ul>"
                ),
            )
        ],
    )
