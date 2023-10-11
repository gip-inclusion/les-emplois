from datetime import timedelta

import pytest
from dateutil.relativedelta import relativedelta
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.utils.http import urlencode
from freezegun import freeze_time

from itou.approvals.enums import ProlongationReason
from itou.approvals.models import Prolongation
from itou.siaes.enums import SiaeKind
from itou.utils.storage.s3 import S3Upload
from itou.utils.widgets import DuetDatePickerWidget
from tests.approvals.factories import ProlongationFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.utils.htmx.test import assertSoupEqual, update_page_with_htmx
from tests.utils.test import parse_response_to_soup


@pytest.mark.usefixtures("unittest_compatibility")
@freeze_time("2023-08-23")
class ApprovalProlongationTest(TestCase):
    PROLONGATION_EMAIL_REPORT_TEXT = "- Fiche bilan :"

    def setUp(self):
        """
        Create test objects.
        """
        super().setUp()

        self.prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
        self.prescriber = self.prescriber_organization.members.first()

        self._setup_with_siae_kind(SiaeKind.EI)

    def _setup_with_siae_kind(self, siae_kind: SiaeKind):
        today = timezone.localdate()
        self.job_application = JobApplicationFactory(
            with_approval=True,
            # Ensure that the job_application cannot be canceled.
            hiring_start_at=today - relativedelta(days=1),
            approval__start_at=today - relativedelta(months=12),
            approval__end_at=today + relativedelta(months=2),
            to_siae__kind=siae_kind,
        )
        self.siae = self.job_application.to_siae
        self.siae_user = self.job_application.to_siae.members.first()
        self.approval = self.job_application.approval
        assert 0 == self.approval.prolongation_set.count()

    def test_prolong_approval_view(self):
        """
        Test the creation of a prolongation.
        """

        self.client.force_login(self.siae_user)

        back_url = reverse("search:siaes_home")
        params = urlencode({"back_url": back_url})
        url = reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk})
        url = f"{url}?{params}"

        response = self.client.get(url)
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
        response = self.client.post(url, data=post_data)
        self.assertContains(response, escape("Sélectionnez un choix valide."))

        # With valid reason
        reason = ProlongationReason.SENIOR
        end_at = self.approval.end_at + relativedelta(days=30)

        post_data = {
            "end_at": end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "reason": reason,
            "email": self.prescriber.email,
            "contact_email": self.faker.email(),
            "contact_phone": self.faker.phone_number(),
            "report_file_path": "prolongation_report/memento-mori.xslx",
            "uploaded_file_name": "report_file.xlsx",
            "prescriber_organization": self.prescriber_organization.pk,
            # Preview.
            "preview": "1",
        }

        # Go to preview.
        response = self.client.post(url, data=post_data)
        assert response.status_code == 200
        assert response.context["preview"] is True

        # Save to DB.
        del post_data["preview"]
        post_data["save"] = 1

        response = self.client.post(url, data=post_data)
        assert response.status_code == 302
        self.assertRedirects(response, back_url)

        prolongation_request = self.approval.prolongationrequest_set.get()
        assert prolongation_request.created_by == self.siae_user
        assert prolongation_request.declared_by == self.siae_user
        assert prolongation_request.declared_by_siae == self.job_application.to_siae
        assert prolongation_request.validated_by == self.prescriber
        assert prolongation_request.reason == post_data["reason"]

        # An email should have been sent to the chosen authorized prescriber.
        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert len(email.to) == 1
        assert email.to[0] == post_data["email"]

    def test_prolong_approval_view_prepopulates_SENIOR_CDI(self):
        self.client.force_login(self.siae_user)
        response = self.client.post(
            reverse("approvals:prolongation_form_for_reason", kwargs={"approval_id": self.approval.pk}),
            {"reason": ProlongationReason.SENIOR_CDI},
        )
        soup = parse_response_to_soup(response)
        [end_at_field] = soup.select("[name=end_at]")
        assert str(end_at_field.parent) == self.snapshot(name="value is set to max_end_at")

    def test_prolong_approval_view_bad_reason(self):
        self.client.force_login(self.siae_user)
        end_at = timezone.localdate() + relativedelta(months=1)
        response = self.client.post(
            reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk}),
            {
                "end_at": end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
                "reason": "invalid",
                "email": self.prescriber.email,
            },
        )
        self.assertContains(
            response,
            '<div class="invalid-feedback">Sélectionnez un choix valide. invalid n’en fait pas partie.</div>',
            count=1,
        )

    def test_prolong_approval_view_no_end_at(self):
        self.client.force_login(self.siae_user)
        response = self.client.post(
            reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk}),
            {
                # end_at is missing.
                "reason": ProlongationReason.SENIOR,
                "email": self.prescriber.email,
            },
        )
        soup = parse_response_to_soup(response)
        [end_at_field] = soup.select("[name=end_at]")
        assert str(end_at_field.parent) == self.snapshot()

    def test_htmx_on_reason(self):
        self.client.force_login(self.siae_user)
        response = self.client.get(
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
        response = self.client.post(
            reverse("approvals:prolongation_form_for_reason", kwargs={"approval_id": self.approval.pk}),
            data,
        )
        update_page_with_htmx(
            page,
            "#id_reason_2",  # RQTH
            response,
        )
        response = self.client.post(
            reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk}),
            data,
        )
        assert response.status_code == 200
        fresh_page = parse_response_to_soup(response, selector="#main")
        assertSoupEqual(page, fresh_page)

    @freeze_time("2023-08-23")
    def test_end_at_limits(self):
        assert len(ProlongationReason.choices) == 6

        self.client.force_login(self.siae_user)
        for end_at, reason in [
            (self.approval.end_at + timedelta(days=10 * 365), ProlongationReason.SENIOR_CDI),
            (self.approval.end_at + timedelta(days=365), ProlongationReason.COMPLETE_TRAINING),
            (self.approval.end_at + timedelta(days=365), ProlongationReason.RQTH),
            (self.approval.end_at + timedelta(days=365), ProlongationReason.SENIOR),
            (self.approval.end_at + timedelta(days=365), ProlongationReason.PARTICULAR_DIFFICULTIES),
            # Since December 1, 2021, HEALTH_CONTEXT reason can no longer be used
        ]:
            with self.subTest(reason):
                response = self.client.post(
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
                assert str(end_at_field.parent) == self.snapshot(name=reason)

    def test_end_at_with_existing_prolongation(self):
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
            self.client.force_login(self.siae_user)
            url = reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk})
            response = self.client.post(
                url,
                data={
                    "reason": reason,
                    # Reach RQTH max duration of 3 years.
                    "end_at": self.approval.end_at + timedelta(days=3 * 365 + 1),
                    "email": self.prescriber.email,
                    "prescriber_organization": self.prescriber_organization.pk,
                },
            )
            max_end_at = self.approval.end_at + timedelta(days=3 * 365)
            self.assertContains(
                response,
                f"""
                <div class="invalid-feedback">
                    Assurez-vous que cette valeur est inférieure ou égale à {max_end_at:%d/%m/%Y}.
                </div>
                """,
                html=True,
                count=1,
            )
            self.assertQuerySetEqual(Prolongation.objects.all(), [prolongation])

    def test_prolong_approval_view_without_prescriber(self):
        """
        Test the creation of a prolongation without prescriber.
        """

        self.client.force_login(self.siae_user)

        back_url = reverse("search:siaes_home")
        params = urlencode({"back_url": back_url})
        url = reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk})
        url = f"{url}?{params}"

        response = self.client.get(url)
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
        response = self.client.post(url, data=post_data)
        assert response.status_code == 200
        assert response.context["preview"] is True

        # Save to DB.
        del post_data["preview"]
        post_data["save"] = 1

        response = self.client.post(url, data=post_data)
        assert response.status_code == 302
        self.assertRedirects(response, back_url)

        assert 1 == self.approval.prolongation_set.count()

        prolongation = self.approval.prolongation_set.first()
        assert prolongation.created_by == self.siae_user
        assert prolongation.declared_by == self.siae_user
        assert prolongation.declared_by_siae == self.job_application.to_siae
        assert prolongation.validated_by is None
        assert prolongation.reason == post_data["reason"]

        # No email should have been sent.
        assert len(mail.outbox) == 0

    def test_prolongation_report_file_fields(self):
        # Check S3 parameters / hidden fields mandatory for report file upload

        self._setup_with_siae_kind(SiaeKind.AI)
        self.client.force_login(self.siae_user)
        url = reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk})
        response = self.client.get(url)

        assert response.status_code == 200

        s3_upload = S3Upload(kind="prolongation_report")

        # Check target S3 bucket URL
        self.assertContains(response, s3_upload.form_values["url"])

        # Config variables: same tests as for apply/resume
        s3_upload.config.pop("upload_expiration")
        for value in s3_upload.config.values():
            self.assertContains(response, value)

        assert s3_upload.config["key_path"] == "prolongation_report"
        assert (
            s3_upload.config["allowed_mime_types"]
            == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    def test_prolongation_report_file(self):
        # Check that report file object is saved and linked to prolongation
        # Bad reason types are checked by UI (JS) and ultimately by DB constraints

        self._setup_with_siae_kind(SiaeKind.AI)
        self.client.force_login(self.siae_user)
        url = reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk})
        response = self.client.get(url)

        reason = ProlongationReason.RQTH
        end_at = self.approval.end_at + relativedelta(days=30)

        post_data = {
            "end_at": end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "reason": reason,
            "email": self.prescriber.email,
            "contact_email": self.faker.email(),
            "contact_phone": self.faker.phone_number(),
            "report_file_path": "prolongation_report/memento-mori.xslx",
            "uploaded_file_name": "report_file.xlsx",
            "prescriber_organization": self.prescriber_organization.pk,
            "save": "1",
        }

        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        prolongation_request = self.approval.prolongationrequest_set.get()
        assert prolongation_request.report_file
        assert prolongation_request.report_file.key == "prolongation_report/memento-mori.xslx"

        [email] = mail.outbox
        assert email.to == [post_data["email"]]
        assert email.subject == f"Demande de prolongation du PASS IAE de {self.approval.user.get_full_name()}"
        assert prolongation_request.report_file.link in email.body
        assert self.PROLONGATION_EMAIL_REPORT_TEXT in email.body

    def test_check_single_prescriber_organization(self):
        self.client.force_login(self.siae_user)
        url = reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk})
        self.client.get(url)

        reason = ProlongationReason.SENIOR
        end_at = self.approval.end_at + relativedelta(days=30)

        post_data = {
            "end_at": end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "reason": reason,
            "email": self.prescriber.email,
            "contact_email": self.faker.email(),
            "contact_phone": self.faker.phone_number(),
            "report_file_path": "prolongation_report/memento-mori.xslx",
            "uploaded_file_name": "report_file.xlsx",
            "edit": "1",
        }
        response = self.client.post(url, data=post_data)

        self.assertContains(response, self.prescriber_organization)
        self.assertNotContains(response, "Sélectionnez l'organisation du prescripteur habilité")

    def test_check_multiple_prescriber_organization(self):
        # Link prescriber to another prescriber organization
        other_prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
        other_prescriber_organization.members.add(self.prescriber)

        self.client.force_login(self.siae_user)
        url = reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk})
        self.client.get(url)

        reason = ProlongationReason.SENIOR
        end_at = self.approval.end_at + relativedelta(days=30)

        post_data = {
            "end_at": end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "reason": reason,
            "email": self.prescriber.email,
            "contact_email": self.faker.email(),
            "contact_phone": self.faker.phone_number(),
            "report_file_path": "prolongation_report/memento-mori.xslx",
            "uploaded_file_name": "report_file.xlsx",
            "edit": "1",
        }
        response = self.client.post(url, data=post_data)

        self.assertContains(response, self.prescriber_organization)
        self.assertContains(response, other_prescriber_organization)

        error_msg = parse_response_to_soup(response, selector="div#check_prescriber_email .invalid-feedback")
        assert str(error_msg) == self.snapshot(name="prescriber is member of many organizations")

    def test_check_invalid_prescriber(self):
        unauthorized_prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=False)
        prescriber = unauthorized_prescriber_organization.members.first()

        self.client.force_login(self.siae_user)
        url = reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk})
        self.client.get(url)

        reason = ProlongationReason.SENIOR
        end_at = self.approval.end_at + relativedelta(days=30)

        post_data = {
            "end_at": end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "reason": reason,
            "email": prescriber.email,
            "contact_email": self.faker.email(),
            "contact_phone": self.faker.phone_number(),
            "report_file_path": "prolongation_report/memento-mori.xslx",
            "uploaded_file_name": "report_file.xlsx",
            "edit": "1",
        }
        response = self.client.post(url, data=post_data)

        error_msg = parse_response_to_soup(response, selector="input#id_email + .invalid-feedback")
        assert str(error_msg) == self.snapshot(name="unknown authorized prescriber")

    def test_prolongation_without_report_file(self):
        # Check with default setup kind: EI
        self.client.force_login(self.siae_user)
        url = reverse("approvals:declare_prolongation", kwargs={"approval_id": self.approval.pk})
        response = self.client.get(url)

        reason = ProlongationReason.SENIOR
        end_at = self.approval.end_at + relativedelta(days=30)

        post_data = {
            "end_at": end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "reason": reason,
            "email": self.prescriber.email,
            "contact_email": self.faker.email(),
            "contact_phone": self.faker.phone_number(),
            "prescriber_organization": self.prescriber_organization.pk,
            "save": "1",
        }

        response = self.client.post(url, data=post_data)

        assert response.status_code == 302
        assert len(mail.outbox) == 1

        email = mail.outbox[0]

        assert len(email.to) == 1
        assert email.to[0] == post_data["email"]
        assert email.subject == f"Demande de prolongation du PASS IAE de {self.approval.user.get_full_name()}"

        prolongation_request = self.approval.prolongationrequest_set.get()
        assert not prolongation_request.report_file
        assert self.PROLONGATION_EMAIL_REPORT_TEXT not in email.body
