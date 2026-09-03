import uuid
from datetime import date, timedelta

import pytest
from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.utils.http import urlencode
from freezegun import freeze_time
from pytest_django.asserts import (
    assertContains,
    assertMessages,
    assertNotContains,
    assertQuerySetEqual,
    assertRedirects,
)

from itou.approvals.enums import ProlongationReason, ProlongationRequestStatus
from itou.approvals.models import Prolongation
from itou.approvals.perms import prolongation_derogation_session_key
from itou.companies.enums import CompanyKind
from itou.job_applications.enums import JobApplicationState
from itou.utils.tokens import prolongation_derogation_token_generator
from itou.utils.widgets import DuetDatePickerWidget
from tests.approvals.factories import (
    ApprovalFactory,
    ProlongationFactory,
    ProlongationRequestFactory,
    SuspensionFactory,
)
from tests.companies.factories import CompanyFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.utils.htmx.testing import assertSoupEqual, update_page_with_htmx
from tests.utils.testing import parse_response_to_soup, pretty_indented


PRESCRIBER_ORGANIZATION_EMPTY_LABEL = "Sélectionnez l'organisation du prescripteur habilité"


class TestApprovalProlongation:
    PROLONGATION_EMAIL_REPORT_TEXT = "- Fiche bilan :"

    @pytest.fixture(autouse=True)
    def setup_method(self):
        with freeze_time("2023-08-23"):
            self.prescriber_organization = PrescriberOrganizationFactory(authorized=True, with_membership=True)
            self.prescriber = self.prescriber_organization.members.first()

            self._setup_with_company_kind(CompanyKind.EI)

            yield

    def _setup_with_company_kind(self, siae_kind: CompanyKind):
        # freeze_time does not work inside factories
        today = timezone.localdate()
        self.job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            with_approval=True,
            # Ensure that the job_application cannot be canceled.
            hiring_start_at=today - relativedelta(days=1),
            approval__start_at=today - relativedelta(months=12),
            approval__end_at=today + relativedelta(months=2),
            to_company__kind=siae_kind,
        )
        self.siae = self.job_application.to_company
        self.employer = self.job_application.to_company.members.first()
        self.approval = self.job_application.approval
        assert 0 == self.approval.prolongation_set.count()

    def test_prolong_approval_view(self, client, mailoutbox, faker):
        """
        Test the creation of a prolongation.
        """

        client.force_login(self.employer)

        back_url = reverse("dashboard:index")
        params = urlencode({"back_url": back_url})
        url = reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk})
        url = f"{url}?{params}"

        response = client.get(url)
        assert response.status_code == 200
        assert response.context["preview"] is False

        # Since December 1, 2021, health context reason can no longer be used
        reason = ProlongationReason.HEALTH_CONTEXT
        end_at = self.approval.end_at + relativedelta(days=30)
        post_data = {
            "end_at": end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "reason": reason,
            "email": self.prescriber.email,
            # Preview.
            "preview": "1",
        }
        response = client.post(url, data=post_data)
        assertContains(response, escape("Sélectionnez un choix valide."))

        # With valid reason
        reason = ProlongationReason.SENIOR
        end_at = self.approval.end_at + relativedelta(days=30)

        post_data = {
            "end_at": end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "reason": reason,
            "email": self.prescriber.email,
            "contact_email": faker.email(),
            "contact_phone": faker.phone_number(),
            "prescriber_organization": self.prescriber_organization.pk,
            # Preview.
            "preview": "1",
        }

        # Go to preview.
        response = client.post(url, data=post_data)
        assert response.status_code == 200
        assert response.context["preview"] is True

        # Save to DB.
        del post_data["preview"]
        post_data["save"] = 1

        response = client.post(url, data=post_data)
        assert response.status_code == 302
        assertRedirects(response, back_url)

        prolongation_request = self.approval.prolongationrequest_set.get()
        assert prolongation_request.created_by == self.employer
        assert prolongation_request.declared_by == self.employer
        assert prolongation_request.declared_by_siae == self.job_application.to_company
        assert prolongation_request.assigned_to == self.prescriber
        assert prolongation_request.reason == post_data["reason"]
        assert not prolongation_request.report_file

        # An email should have been sent to the chosen authorized prescriber.
        assert len(mailoutbox) == 1
        email = mailoutbox[0]
        assert len(email.to) == 1
        assert email.to[0] == post_data["email"]

    def test_approval_prolongation_with_other_employer(self, client):
        """
        An employer should not be able to declare a prolongation for an approval that belongs to an employee of
        another company
        """
        other_company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        other_employer = other_company.members.first()

        client.force_login(other_employer)

        url = reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk})
        response = client.get(url)
        assert response.status_code == 404

    @pytest.mark.parametrize(
        "view_name",
        [
            "declare_prolongation",
            "prolongation_form_for_reason",
            "check_prescriber_email",
            "check_contact_details",
        ],
    )
    def test_approval_prolongation_with_company_not_subject_to_iae_rules(self, client, view_name):
        """Only a company subject to IAE rules may declare a prolongation."""
        self._setup_with_company_kind(CompanyKind.GEIQ)
        assert not self.siae.is_subject_to_iae_rules
        client.force_login(self.employer)
        url = reverse(f"approvals:{view_name}", kwargs={"approval_id": self.approval.pk})
        response = client.post(url, {"reason": ProlongationReason.SENIOR})
        assert response.status_code == 403

    @pytest.mark.parametrize(
        "view_name",
        [
            "prolongation_form_for_reason",
            "check_prescriber_email",
            "check_contact_details",
        ],
    )
    def test_htmx_fragments_approval_prolongation_with_other_employer(self, client, view_name):
        """
        HTMX fragments views should also deny access to non-related employers
        """
        other_company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        other_employer = other_company.members.first()

        client.force_login(other_employer)

        url = reverse(f"approvals:{view_name}", kwargs={"approval_id": self.approval.pk})
        response = client.post(url, {"reason": ProlongationReason.SENIOR})
        assert response.status_code == 404

    def test_prolong_approval_view_prepopulates_SENIOR_CDI(self, client, snapshot):
        client.force_login(self.employer)
        response = client.post(
            reverse("approvals:prolongation_form_for_reason", kwargs={"approval_id": self.approval.pk}),
            {"reason": ProlongationReason.SENIOR_CDI},
        )
        soup = parse_response_to_soup(response)
        [end_at_field] = soup.select("[name=end_at]")
        assert pretty_indented(end_at_field.parent) == snapshot(name="value is set to max_end_at")

    def test_prolong_approval_view_bad_reason(self, client):
        client.force_login(self.employer)
        end_at = timezone.localdate() + relativedelta(months=1)
        response = client.post(
            reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk}),
            {
                "end_at": end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
                "reason": "invalid",
                "email": self.prescriber.email,
            },
        )
        assertContains(
            response,
            '<div class="invalid-feedback d-block">Sélectionnez un choix valide. invalid n’en fait pas partie.</div>',
            count=1,
        )

    def test_prolongation_approval_view_with_disabled_values(self, settings, client, snapshot):
        """
        Test the deactivation of reasons if too many prolongations have already been created.
        """
        # since 'freeze_time' is called twice with non deterministic dates and
        # since the repo might contain a future version of the 'CGU' (not yet in force),
        # explicitly calling 'accept_legal_terms' below is a tricky alternative
        settings.BYPASS_TERMS_ACCEPTANCE = True

        # This should be several succeeding prolongations but this is good enough for our test
        prolongation = ProlongationFactory(
            approval=self.approval,
            start_at=self.approval.end_at,
            end_at=self.approval.end_at + timedelta(days=365 * 3 + 10),
            reason=ProlongationReason.COMPLETE_TRAINING,
        )
        url = reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk})

        # For reason fields snapshots
        replace_in_attr = [
            (
                "hx-post",
                f"/approvals/declare_prolongation/{self.approval.pk}/prolongation_form_for_reason",
                "/approvals/declare_prolongation/[PK of Approval]/prolongation_form_for_reason",
            )
        ]

        with freeze_time(prolongation.end_at):
            client.force_login(self.employer)
            response = client.get(url)
            # Check the information card
            soup = parse_response_to_soup(response, selector="div:has(> #disabledChoicesCollapseInfo)")
            assert pretty_indented(soup) == snapshot(name="missing_reason_info")
            # Check the reason field
            assert response.context["form"]["reason"].field.widget.disabled_values == {"RQTH"}
            assert {v for v, _label in response.context["form"]["reason"].field._choices} == {
                "COMPLETE_TRAINING",
                "SENIOR",
                "SENIOR_CDI",
            }
            # Check reason field
            soup = parse_response_to_soup(response, selector="div:has(> #id_reason)", replace_in_attr=replace_in_attr)
            assert pretty_indented(soup) == snapshot(name="RQTH disabled")

            # Try using a disabled choice
            response = client.post(url, data={"reason": ProlongationReason.RQTH})
            assertContains(response, "Sélectionnez un choix valide.")

        # Add even more prolongations
        other_prolongation = ProlongationFactory(
            approval=self.approval,
            start_at=prolongation.end_at,
            end_at=prolongation.end_at + timedelta(days=365 * 2),
            reason=ProlongationReason.RQTH,
        )
        with freeze_time(other_prolongation.end_at):
            client.force_login(self.employer)
            response = client.get(url)
            # Check the information card is still there
            soup = parse_response_to_soup(response, selector="div:has(> #disabledChoicesCollapseInfo)")
            assert pretty_indented(soup) == snapshot(name="missing_reason_info")
            # Check the reason field: SENIOR is now also disabled
            assert response.context["form"]["reason"].field.widget.disabled_values == {
                "RQTH",
                "SENIOR",
            }
            assert {v for v, _label in response.context["form"]["reason"].field._choices} == {
                "COMPLETE_TRAINING",
                "SENIOR_CDI",
            }
            # Check reason field
            soup = parse_response_to_soup(response, selector="div:has(> #id_reason)", replace_in_attr=replace_in_attr)
            assert pretty_indented(soup) == snapshot(name="RQTH & SENIOR disabled")

    def test_prolong_approval_view_no_end_at(self, client, snapshot):
        client.force_login(self.employer)
        response = client.post(
            reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk}),
            {
                # end_at is missing.
                "reason": ProlongationReason.SENIOR,
                "email": self.prescriber.email,
            },
        )
        soup = parse_response_to_soup(response)
        [end_at_field] = soup.select("[name=end_at]")
        assert pretty_indented(end_at_field.parent) == snapshot()

    def test_htmx_on_reason(self, client):
        client.force_login(self.employer)
        response = client.get(
            reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk}),
        )
        assert response.status_code == 200
        page = parse_response_to_soup(response, selector="#main")
        data = {
            "reason": ProlongationReason.RQTH,
            # Workaround the validation of the initial page by providing enough data.
            "end_at": self.approval.end_at + relativedelta(days=30),
            "email": self.prescriber.email,
        }
        response = client.post(
            reverse("approvals:prolongation_form_for_reason", kwargs={"approval_id": self.approval.pk}),
            data,
        )
        update_page_with_htmx(
            page,
            '#id_reason input[value="RQTH"]',
            response,
        )
        response = client.post(
            reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk}),
            data,
        )
        assert response.status_code == 200
        fresh_page = parse_response_to_soup(response, selector="#main")
        assertSoupEqual(page, fresh_page)

    def test_htmx_on_reason_with_back_url(self, client, snapshot):
        client.force_login(self.employer)
        back_url = "/somewhere/over/the/rainbow"
        page_url = reverse(
            "approvals:declare_prolongation",
            kwargs={"approval_id": self.approval.pk},
            query={"back_url": back_url},
        )
        response = client.get(page_url)
        assert response.status_code == 200
        page = parse_response_to_soup(response, selector="#main")
        [reset_button] = page.select("a[aria-label='Annuler la saisie de ce formulaire']")
        assert pretty_indented(reset_button) == snapshot(name="reset button with correct back_url")

        [reason] = page.select('#id_reason input[value="RQTH"]')
        expected_hx_post = reverse(
            "approvals:prolongation_form_for_reason",
            kwargs={"approval_id": self.approval.pk},
            query={"back_url": back_url},
        )
        assert reason["hx-post"] == expected_hx_post
        data = {
            "reason": ProlongationReason.RQTH,
            # Workaround the validation of the initial page by providing enough data.
            "end_at": self.approval.end_at + relativedelta(days=30),
            "email": self.prescriber.email,
        }
        response = client.post(reason["hx-post"], data)
        update_page_with_htmx(
            page,
            '#id_reason input[value="RQTH"]',
            response,
        )
        response = client.post(page_url, data)
        assert response.status_code == 200
        fresh_page = parse_response_to_soup(response, selector="#main")
        assertSoupEqual(page, fresh_page)
        [reset_button] = fresh_page.select("a[aria-label='Annuler la saisie de ce formulaire']")
        assert pretty_indented(reset_button) == snapshot(name="reset button with correct back_url")

    @freeze_time("2023-08-23")
    def test_end_at_limits(self, client, snapshot, subtests):
        assert len(ProlongationReason.choices) == 6

        client.force_login(self.employer)
        for end_at, reason in [
            (self.approval.end_at + timedelta(days=10 * 365), ProlongationReason.SENIOR_CDI),
            (self.approval.end_at + timedelta(days=365), ProlongationReason.COMPLETE_TRAINING),
            (self.approval.end_at + timedelta(days=365), ProlongationReason.RQTH),
            (self.approval.end_at + timedelta(days=365), ProlongationReason.SENIOR),
            (self.approval.end_at + timedelta(days=365), ProlongationReason.PARTICULAR_DIFFICULTIES),
            # Since December 1, 2021, HEALTH_CONTEXT reason can no longer be used
        ]:
            with subtests.test(reason.label):
                response = client.post(
                    reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk}),
                    data={
                        "reason": reason,
                        "end_at": end_at,
                        "email": self.prescriber.email,
                        # Missing prescriber organization.
                    },
                )
                soup = parse_response_to_soup(response)
                [end_at_field] = soup.select("[name=end_at]")
                assert pretty_indented(end_at_field.parent) == snapshot(name=reason)

    def test_end_at_with_existing_prolongation(self, client, snapshot):
        reason = ProlongationReason.RQTH
        # RQTH max prolongation duration is 3 years, this prolongation consumes 2.5 years.
        # Only 183 days remain.
        end_at = self.approval.end_at + timedelta(days=2 * 365 + 182)
        prolongation = ProlongationFactory(
            approval=self.approval,
            start_at=self.approval.end_at,
            end_at=end_at,
            reason=reason,
        )
        with freeze_time(end_at):
            client.force_login(self.employer)

            # Check htmx response
            response = client.post(
                reverse("approvals:prolongation_form_for_reason", kwargs={"approval_id": self.approval.pk}),
                data={
                    "reason": reason,
                },
            )
            # Check the information card
            soup = parse_response_to_soup(response, selector="div:has(> #maxEndAtCollapseInfo)")
            assert pretty_indented(soup) == snapshot(name="max_limit_info")

            url = reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk})
            response = client.post(
                url,
                data={
                    "reason": reason,
                    # Reach RQTH max duration of 3 years.
                    "end_at": self.approval.end_at + timedelta(days=3 * 365 + 1),
                    "email": self.prescriber.email,
                    "prescriber_organization": self.prescriber_organization.pk,
                },
            )
            soup = parse_response_to_soup(response, selector="div:has(> #maxEndAtCollapseInfo)")
            assert pretty_indented(soup) == snapshot(name="max_limit_info")
            max_end_at = self.approval.end_at + timedelta(days=3 * 365)
            assertContains(
                response,
                f"""
                <div class="invalid-feedback d-block">
                    Assurez-vous que cette valeur est inférieure ou égale à {max_end_at:%d/%m/%Y}.
                </div>
                """,
                html=True,
                count=1,
            )
            assertQuerySetEqual(Prolongation.objects.all(), [prolongation])

    def test_prolong_approval_view_without_prescriber(self, client, mailoutbox):
        """
        Test the creation of a prolongation without prescriber.
        """

        client.force_login(self.employer)

        back_url = reverse("dashboard:index")
        params = urlencode({"back_url": back_url})
        url = reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk})
        url = f"{url}?{params}"

        response = client.get(url)
        assert response.status_code == 200
        assert response.context["preview"] is False

        reason = ProlongationReason.COMPLETE_TRAINING
        end_at = self.approval.end_at + relativedelta(days=30)

        post_data = {
            "end_at": end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "reason": reason,
            # Preview.
            "preview": "1",
        }

        # Go to preview.
        response = client.post(url, data=post_data)
        assert response.status_code == 200
        assert response.context["preview"] is True

        # Save to DB.
        del post_data["preview"]
        post_data["save"] = 1

        response = client.post(url, data=post_data)
        assert response.status_code == 302
        assertRedirects(response, back_url)

        assert 1 == self.approval.prolongation_set.count()

        prolongation = self.approval.prolongation_set.first()
        assert prolongation.created_by == self.employer
        assert prolongation.declared_by == self.employer
        assert prolongation.declared_by_siae == self.job_application.to_company
        assert prolongation.validated_by is None
        assert prolongation.reason == post_data["reason"]

        # No email should have been sent.
        assert len(mailoutbox) == 0

    def test_check_single_prescriber_organization(self, client, faker):
        client.force_login(self.employer)
        url = reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk})
        client.get(url)

        reason = ProlongationReason.SENIOR
        end_at = self.approval.end_at + relativedelta(days=30)

        post_data = {
            "end_at": end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "reason": reason,
            "email": self.prescriber.email,
            "contact_email": faker.email(),
            "contact_phone": faker.phone_number(),
            "edit": "1",
        }
        response = client.post(url, data=post_data)

        assertContains(response, self.prescriber_organization)
        assertNotContains(response, PRESCRIBER_ORGANIZATION_EMPTY_LABEL, html=True)

    def test_check_multiple_prescriber_organization(self, client, snapshot, faker):
        # Link prescriber to another prescriber organization
        other_prescriber_organization = PrescriberOrganizationFactory(authorized=True, with_membership=True)
        other_prescriber_organization.members.add(self.prescriber)

        inactive_prescriber_organization = PrescriberOrganizationFactory(authorized=True, with_membership=True)
        PrescriberMembershipFactory(
            user=self.prescriber,
            organization=inactive_prescriber_organization,
            is_active=False,
        )

        client.force_login(self.employer)
        url = reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk})
        client.get(url)

        reason = ProlongationReason.SENIOR
        end_at = self.approval.end_at + relativedelta(days=30)

        post_data = {
            "end_at": end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "reason": reason,
            "email": self.prescriber.email,
            "contact_email": faker.email(),
            "contact_phone": faker.phone_number(),
            "edit": "1",
        }
        response = client.post(url, data=post_data)
        assertContains(response, PRESCRIBER_ORGANIZATION_EMPTY_LABEL, html=True)

        assertContains(response, self.prescriber_organization)
        assertContains(response, other_prescriber_organization)
        assertNotContains(response, inactive_prescriber_organization)

        error_msg = parse_response_to_soup(response, selector="div#check_prescriber_email .invalid-feedback")
        assert pretty_indented(error_msg) == snapshot(name="prescriber is member of many organizations")

    def test_check_invalid_prescriber(self, client, snapshot, faker):
        unauthorized_prescriber_organization = PrescriberOrganizationFactory(authorized=False, with_membership=True)
        prescriber = unauthorized_prescriber_organization.members.first()

        client.force_login(self.employer)
        url = reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk})
        client.get(url)

        reason = ProlongationReason.SENIOR
        end_at = self.approval.end_at + relativedelta(days=30)

        post_data = {
            "end_at": end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "reason": reason,
            "email": prescriber.email,
            "contact_email": faker.email(),
            "contact_phone": faker.phone_number(),
            "edit": "1",
        }
        response = client.post(url, data=post_data)

        error_msg = parse_response_to_soup(response, selector="div#id_email_error > .invalid-feedback")
        assert pretty_indented(error_msg) == snapshot(name="unknown authorized prescriber")


@pytest.mark.usefixtures("temporary_bucket")
def test_prolongation_report_file(client, mocker, faker, xlsx_file, mailoutbox):
    """
    Check that report file object is saved and linked to prolongation
    Bad reason types are checked by UI (JS) and ultimately by DB constraints
    """
    mocker.patch(
        "itou.files.models.uuid.uuid4",
        return_value=uuid.UUID("11111111-1111-1111-1111-111111111111"),
    )
    prescriber_organization = PrescriberOrganizationFactory(authorized=True, with_membership=True)
    prescriber = prescriber_organization.members.first()

    today = timezone.localdate()
    job_application = JobApplicationFactory(
        sent_by_prescriber_alone=True,
        with_approval=True,
        # Ensure that the job_application cannot be canceled.
        hiring_start_at=today - relativedelta(days=1),
        approval__start_at=today - relativedelta(months=12),
        approval__end_at=today + relativedelta(months=2),
        to_company__kind=CompanyKind.AI,
    )
    employer = job_application.to_company.members.first()
    approval = job_application.approval
    assert 0 == approval.prolongation_set.count()

    client.force_login(employer)
    url = reverse("approvals:declare_prolongation", kwargs={"approval_id": approval.pk})

    post_data = {
        "end_at": (approval.end_at + relativedelta(days=30)).strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        "reason": ProlongationReason.RQTH,
        "email": prescriber.email,
        "contact_email": faker.email(),
        "contact_phone": faker.phone_number(),
        "report_file": xlsx_file,
        "prescriber_organization": prescriber_organization.pk,
        "preview": "1",
    }

    response = client.post(url, data=post_data)
    assert response.status_code == 200
    assert response.context["preview"] is True

    # Save to DB.
    del post_data["preview"]
    del post_data["report_file"]
    post_data["save"] = 1

    response = client.post(url, data=post_data)
    assert response.status_code == 302
    assertRedirects(response, reverse("dashboard:index"))

    prolongation_request = approval.prolongationrequest_set.get()
    assert prolongation_request.report_file
    assert prolongation_request.report_file.key == "prolongation_report/11111111-1111-1111-1111-111111111111.xlsx"

    [email] = mailoutbox
    assert email.to == [post_data["email"]]
    assert email.subject == f"[TEST] Demande de prolongation du PASS IAE de {approval.user.get_inverted_full_name()}"
    assert (
        reverse(
            "approvals:prolongation_request_report_file",
            kwargs={"prolongation_request_id": prolongation_request.pk},
        )
        in email.body
    )
    assert TestApprovalProlongation.PROLONGATION_EMAIL_REPORT_TEXT in email.body


class TestProlongationDerogationLink:
    """The support can hand out a link waiving the prolongation deadline, and only this limit."""

    HTMX_VIEW_NAMES = ["prolongation_form_for_reason", "check_prescriber_email", "check_contact_details"]

    NEW_PROLONGATION_MARKUP = '<form id="new-prolongation-form"'

    def _setup_approval(self, end_at):
        self.job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            with_approval=True,
            approval__start_at=end_at - relativedelta(months=24),
            approval__end_at=end_at,
            # An AI company would add the report file field,
            # whose HTMX and full page renderings differ
            to_company__kind=CompanyKind.EI,
        )
        self.siae = self.job_application.to_company
        self.employer = self.siae.members.first()
        self.approval = self.job_application.approval

    @pytest.fixture(autouse=True)
    def setup_method(self):
        # A PASS IAE that expired more than 6 months ago: the employer cannot prolong it alone
        self._setup_approval(end_at=timezone.localdate() - relativedelta(months=8))
        assert not self.approval.is_open_to_prolongation

    def _derogation_url(self, token, **kwargs):
        """The link the support hands out: it opens the declaration form."""
        return reverse(
            "approvals:prolongation_derogation", kwargs={"approval_id": self.approval.pk, "token": token}, **kwargs
        )

    def _url(self, **kwargs):
        return reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk}, **kwargs)

    def _token(self, company=None):
        return prolongation_derogation_token_generator.make_token(approval=self.approval, company=company or self.siae)

    def _follow_derogation_link(self, client, token=None, **kwargs):
        """Follow the derogation link and return the declaration form page."""
        response = client.get(self._derogation_url(token or self._token(), **kwargs))
        assertRedirects(response, self._url(**kwargs))
        return client.get(response.url)

    def _assert_link_refused(self, response, company=None):
        """The derogation link led nowhere: the employer is sent back with an explicit message."""
        assertRedirects(response, reverse("dashboard:index"))
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Le token n’est peut-être plus valable ou concerne une autre structure "
                    f"que celle actuellement active ({(company or self.siae).display_name}).",
                )
            ],
        )

    def _session_token(self, client, company=None):
        session_key = prolongation_derogation_session_key(approval=self.approval, company=company or self.siae)
        return client.session.get(session_key)

    def test_with_token(self, client):
        client.force_login(self.employer)
        response = self._follow_derogation_link(client)
        assertContains(response, self.NEW_PROLONGATION_MARKUP)

    def test_declare_prolongation(self, client, mailoutbox):
        client.force_login(self.employer)
        back_url = reverse("dashboard:index")
        query = {"back_url": back_url}
        url = self._url(query=query)

        response = self._follow_derogation_link(client, query=query)
        assert response.context["preview"] is False

        post_data = {
            "end_at": (self.approval.end_at + relativedelta(days=30)).strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "reason": ProlongationReason.COMPLETE_TRAINING,
            "preview": "1",
        }
        response = client.post(url, data=post_data)
        assert response.context["preview"] is True

        del post_data["preview"]
        post_data["save"] = 1
        response = client.post(url, data=post_data)
        assertRedirects(response, back_url)

        prolongation = self.approval.prolongation_set.get()
        assert prolongation.declared_by == self.employer
        assert prolongation.declared_by_siae == self.siae
        assert prolongation.start_at == self.approval.end_at
        assert prolongation.reason == ProlongationReason.COMPLETE_TRAINING
        assert not mailoutbox

    def test_without_token(self, client):
        client.force_login(self.employer)
        response = client.get(self._url())
        assert response.status_code == 403

    def test_the_bypass_is_scoped_to_one_approval(self, client):
        # The company hired two job seekers, both PASS IAE are out of the prolongation window
        # but the support only issued a link for one of them
        other_end_at = timezone.localdate() - relativedelta(months=8)
        other_approval = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            with_approval=True,
            approval__start_at=other_end_at - relativedelta(months=24),
            approval__end_at=other_end_at,
            to_company=self.siae,
        ).approval
        client.force_login(self.employer)
        self._follow_derogation_link(client)
        other_url = reverse("approvals:declare_prolongation", kwargs={"approval_id": other_approval.pk})
        assert client.get(other_url).status_code == 403

    def test_before_the_prolongation_window(self, client):
        # A PASS IAE ending in more than 12 months is out of the window too,
        # but no link can rescue it: only the deadline is waivable
        self._setup_approval(end_at=timezone.localdate() + relativedelta(months=18))
        assert not self.approval.is_open_to_prolongation
        assert not self.approval.needs_prolongation_derogation
        client.force_login(self.employer)

        assert client.get(self._url()).status_code == 403
        self._assert_link_refused(client.get(self._derogation_url(self._token())))

    def test_link_is_consumed_by_a_first_prolongation(self, client):
        token = self._token()
        ProlongationFactory(
            approval=self.approval,
            declared_by_siae=self.siae,
            declared_by=self.employer,
            start_at=self.approval.end_at,
            end_at=self.approval.end_at + relativedelta(days=30),
        )
        self.approval.refresh_from_db()
        client.force_login(self.employer)
        self._assert_link_refused(client.get(self._derogation_url(token)))

    def test_link_is_consumed_by_a_first_prolongation_request(self, client):
        # A prolongation request is denied:
        # the PASS IAE is still extendable, but with another link
        token = self._token()
        ProlongationRequestFactory(
            approval=self.approval,
            declared_by_siae=self.siae,
            declared_by=self.employer,
            status=ProlongationRequestStatus.DENIED,
        )
        client.force_login(self.employer)
        assert self.approval.needs_prolongation_derogation
        self._assert_link_refused(client.get(self._derogation_url(token)))

    def test_a_new_link_can_be_issued_after_a_prolongation(self, client):
        # The PASS IAE is still out of the prolongation window after a first prolongation:
        # the consumed link cannot be reused, but the support can issue another one
        ProlongationFactory(
            approval=self.approval,
            declared_by_siae=self.siae,
            declared_by=self.employer,
            start_at=self.approval.end_at,
            end_at=self.approval.end_at + relativedelta(days=30),
        )
        self.approval.refresh_from_db()
        assert self.approval.needs_prolongation_derogation
        client.force_login(self.employer)
        assertContains(self._follow_derogation_link(client, self._token()), self.NEW_PROLONGATION_MARKUP)

    def test_invalid_token(self, client):
        invalid_token = "ddt9as-f88cd08908264f2e9de6"
        client.force_login(self.employer)
        self._assert_link_refused(client.get(self._derogation_url(invalid_token)))

    def test_invalid_token_inside_the_prolongation_window(self, client):
        # The approval could be prolonged without any token:
        # a bogus one must not be accepted anyway
        invalid_token = "ddt9as-f88cd08908264f2e9de6"
        self._setup_approval(end_at=timezone.localdate() + relativedelta(months=1))
        assert self.approval.is_open_to_prolongation
        client.force_login(self.employer)
        assertContains(client.get(self._url()), self.NEW_PROLONGATION_MARKUP)
        self._assert_link_refused(client.get(self._derogation_url(invalid_token)))

    def test_token_issued_for_another_company(self, client):
        other_company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        derogation_url = self._derogation_url(self._token(company=other_company))
        client.force_login(self.employer)
        self._assert_link_refused(client.get(derogation_url))
        # The company the token was issued for never hired this job seeker
        client.force_login(other_company.members.first())
        self._assert_link_refused(client.get(derogation_url), company=other_company)

    def test_current_company_not_subject_to_iae_rules(self, client):
        geiq = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True)
        JobApplicationFactory(
            sent_by_prescriber_alone=True,
            approval=self.approval,
            job_seeker=self.approval.user,
            to_company=geiq,
            state=JobApplicationState.ACCEPTED,
        )
        client.force_login(geiq.members.first())
        self._assert_link_refused(client.get(self._derogation_url(self._token(company=geiq))), company=geiq)

    def test_expired_token(self, client, settings):
        # Moving through time brings a new version of the "CGU" into force
        settings.BYPASS_TERMS_ACCEPTANCE = True
        with freeze_time("2025-08-21") as frozen_time:
            # Fixed dates, so that the PASS IAE stays out of the prolongation window
            # and out of the waiting period for the whole test
            self._setup_approval(end_at=date(2024, 6, 30))
            assert not self.approval.is_open_to_prolongation
            token = self._token()
            frozen_time.move_to("2025-11-18")  # 89 days later
            client.force_login(self.employer)
            assertContains(self._follow_derogation_link(client, token), self.NEW_PROLONGATION_MARKUP)
            frozen_time.move_to("2025-11-20")  # 91 days later
            client.force_login(self.employer)
            self._assert_link_refused(client.get(self._derogation_url(token)))

    def test_suspended_approval(self, client):
        SuspensionFactory(
            approval=self.approval,
            siae=self.siae,
            start_at=timezone.localdate() - relativedelta(days=1),
            end_at=timezone.localdate() + relativedelta(days=1),
        )
        client.force_login(self.employer)
        self._assert_link_refused(client.get(self._derogation_url(self._token())))

    def test_pending_prolongation_request(self, client):
        ProlongationRequestFactory(approval=self.approval, declared_by_siae=self.siae)
        client.force_login(self.employer)
        self._assert_link_refused(client.get(self._derogation_url(self._token())))

    def test_not_the_latest_approval(self, client):
        ApprovalFactory(user=self.approval.user)
        client.force_login(self.employer)
        self._assert_link_refused(client.get(self._derogation_url(self._token())))

    def test_waiting_period_has_elapsed(self, client):
        # Beyond the 2 years waiting period the job seeker has no latest approval anymore
        self._setup_approval(end_at=timezone.localdate() - relativedelta(months=30))
        client.force_login(self.employer)
        self._assert_link_refused(client.get(self._derogation_url(self._token())))

    def test_stale_token_is_removed_from_the_session(self, client):
        client.force_login(self.employer)
        token = self._token()
        self._follow_derogation_link(client, token)
        assert self._session_token(client) == token

        # Another declaration consumes the link
        ProlongationFactory(
            approval=self.approval,
            declared_by_siae=self.siae,
            declared_by=self.employer,
            start_at=self.approval.end_at,
            end_at=self.approval.end_at + relativedelta(days=30),
        )
        assert client.get(self._url()).status_code == 403
        assert self._session_token(client) is None

    def test_valid_token_is_kept_in_the_session(self, client):
        client.force_login(self.employer)
        token = self._token()
        assertContains(self._follow_derogation_link(client, token), self.NEW_PROLONGATION_MARKUP)
        assertContains(client.get(self._url()), self.NEW_PROLONGATION_MARKUP)
        assert self._session_token(client) == token

    @pytest.mark.parametrize("view_name", HTMX_VIEW_NAMES)
    def test_htmx_fragments(self, client, view_name):
        client.force_login(self.employer)
        data = {"reason": ProlongationReason.SENIOR}
        url = reverse(f"approvals:{view_name}", kwargs={"approval_id": self.approval.pk})
        assert client.post(url, data).status_code == 403
        self._follow_derogation_link(client)
        assert client.post(url, data).status_code == 200
        ProlongationFactory(
            approval=self.approval,
            declared_by_siae=self.siae,
            declared_by=self.employer,
            start_at=self.approval.end_at,
            end_at=self.approval.end_at + relativedelta(days=30),
        )
        assert client.post(url, data).status_code == 403

    def test_check_prescriber_email_button(self, client):
        client.force_login(self.employer)
        page = parse_response_to_soup(self._follow_derogation_link(client), selector="#main")
        [reason] = page.select('#id_reason input[value="RQTH"]')
        data = {
            "reason": ProlongationReason.RQTH,
            # Workaround the validation of the initial page by providing enough data
            "end_at": self.approval.end_at + relativedelta(days=30),
            "email": PrescriberOrganizationFactory(authorized=True, with_membership=True).members.first().email,
        }
        update_page_with_htmx(page, '#id_reason input[value="RQTH"]', client.post(reason["hx-post"], data))
        [button] = page.select("#check_prescriber_email button")
        assert client.post(button["hx-post"], data).status_code == 200
