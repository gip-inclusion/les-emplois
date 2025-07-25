import uuid
from datetime import timedelta

import pytest
from dateutil.relativedelta import relativedelta
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.utils.http import urlencode
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertQuerySetEqual, assertRedirects

from itou.approvals.enums import ProlongationReason
from itou.approvals.models import Prolongation
from itou.companies.enums import CompanyKind
from itou.utils.widgets import DuetDatePickerWidget
from tests.approvals.factories import ProlongationFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationWithMembershipFactory
from tests.utils.htmx.test import assertSoupEqual, update_page_with_htmx
from tests.utils.test import parse_response_to_soup, pretty_indented


class TestApprovalProlongation:
    PROLONGATION_EMAIL_REPORT_TEXT = "- Fiche bilan :"

    @pytest.fixture(autouse=True)
    def setup_method(self):
        with freeze_time("2023-08-23"):
            self.prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
            self.prescriber = self.prescriber_organization.members.first()

            self._setup_with_company_kind(CompanyKind.EI)

            yield

    def _setup_with_company_kind(self, siae_kind: CompanyKind):
        # freeze_time does not work inside factories
        today = timezone.localdate()
        self.job_application = JobApplicationFactory(
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

        back_url = reverse("search:employers_home")
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
        assert prolongation_request.validated_by == self.prescriber
        assert prolongation_request.reason == post_data["reason"]
        assert not prolongation_request.report_file

        # An email should have been sent to the chosen authorized prescriber.
        assert len(mailoutbox) == 1
        email = mailoutbox[0]
        assert len(email.to) == 1
        assert email.to[0] == post_data["email"]

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
            '<div class="invalid-feedback">Sélectionnez un choix valide. invalid n’en fait pas partie.</div>',
            count=1,
        )

    def test_prolongation_approval_view_with_disabled_values(self, client, snapshot):
        """
        Test the deactivation of reasons if too many prolongations have already been created.
        """
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
            "#id_reason",  # RQTH
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

        [reason] = page.select("#id_reason")
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
            "#id_reason",  # RQTH
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
                <div class="invalid-feedback">
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

        back_url = reverse("search:employers_home")
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
        assertNotContains(response, "Sélectionnez l'organisation du prescripteur habilité")

    def test_check_multiple_prescriber_organization(self, client, snapshot, faker):
        # Link prescriber to another prescriber organization
        other_prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
        other_prescriber_organization.members.add(self.prescriber)

        inactive_prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
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

        assertContains(response, self.prescriber_organization)
        assertContains(response, other_prescriber_organization)
        assertNotContains(response, inactive_prescriber_organization)

        error_msg = parse_response_to_soup(response, selector="div#check_prescriber_email .invalid-feedback")
        assert pretty_indented(error_msg) == snapshot(name="prescriber is member of many organizations")

    def test_check_invalid_prescriber(self, client, snapshot, faker):
        unauthorized_prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=False)
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

        error_msg = parse_response_to_soup(response, selector="input#id_email + .invalid-feedback")
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
    prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
    prescriber = prescriber_organization.members.first()

    today = timezone.localdate()
    job_application = JobApplicationFactory(
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
    assert email.subject == f"[DEV] Demande de prolongation du PASS IAE de {approval.user.get_full_name()}"
    assert (
        reverse(
            "approvals:prolongation_request_report_file",
            kwargs={"prolongation_request_id": prolongation_request.pk},
        )
        in email.body
    )
    assert TestApprovalProlongation.PROLONGATION_EMAIL_REPORT_TEXT in email.body
