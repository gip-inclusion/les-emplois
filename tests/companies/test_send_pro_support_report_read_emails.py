import datetime

import pytest
from django.core.management import call_command
from freezegun import freeze_time

from itou.companies.models import ProSupportReport
from tests.companies.factories import CompanyMembershipFactory, ProSupportReportFactory
from tests.users.factories import PrescriberFactory


NOW = datetime.datetime(2026, 1, 15, 10, 0, tzinfo=datetime.UTC)
AN_HOUR_AGO = NOW - ProSupportReport.READ_EMAIL_DELAY


@freeze_time(NOW)
class TestSendProSupportReportReadEmails:
    def test_send(self, caplog, django_capture_on_commit_callbacks, mailoutbox):
        report = ProSupportReportFactory(notified_prescriber=PrescriberFactory(), first_read_at=AN_HOUR_AGO)
        CompanyMembershipFactory(company=report.company, user=report.author)
        report_of_an_author_who_left = ProSupportReportFactory(
            notified_prescriber=PrescriberFactory(), first_read_at=AN_HOUR_AGO
        )
        admin = CompanyMembershipFactory(company=report_of_an_author_who_left.company).user

        with django_capture_on_commit_callbacks(execute=True):
            call_command("send_pro_support_report_read_emails", wet_run=True)

        assert sorted(email.to for email in mailoutbox) == sorted([[report.author.email], [admin.email]])
        assert "Sent read emails for 2 pro support reports." in caplog.messages
        assert list(ProSupportReport.objects.values_list("read_email_sent_at", flat=True)) == [NOW, NOW]

    def test_without_admin(self, django_capture_on_commit_callbacks, mailoutbox):
        report = ProSupportReportFactory(notified_prescriber=PrescriberFactory(), first_read_at=AN_HOUR_AGO)
        # The author left, and the only member left is not an admin.
        CompanyMembershipFactory(company=report.company, is_admin=False)

        with django_capture_on_commit_callbacks(execute=True):
            call_command("send_pro_support_report_read_emails", wet_run=True)

        assert mailoutbox == []
        report.refresh_from_db()
        assert report.read_email_sent_at is None  # Sent once auto_attribute_company_admins appoints an admin.

    @pytest.mark.parametrize(
        "kwargs",
        [
            pytest.param({"first_read_at": None}, id="not_read"),
            pytest.param({"first_read_at": AN_HOUR_AGO + datetime.timedelta(minutes=1)}, id="read_recently"),
            pytest.param({"read_email_sent_at": AN_HOUR_AGO}, id="already_sent"),
            pytest.param({"introduction_email_sent_at": AN_HOUR_AGO}, id="prescriber_got_in_touch"),
            pytest.param({"notified_prescriber": None}, id="prescriber_deleted"),
            pytest.param({"company": None}, id="company_deleted"),
        ],
    )
    def test_not_sent(self, kwargs, django_capture_on_commit_callbacks, mailoutbox):
        report = ProSupportReportFactory(
            **{"notified_prescriber": PrescriberFactory(), "first_read_at": AN_HOUR_AGO} | kwargs
        )
        CompanyMembershipFactory(company=report.contract.company, user=report.author)

        with django_capture_on_commit_callbacks(execute=True):
            call_command("send_pro_support_report_read_emails", wet_run=True)

        assert mailoutbox == []
        assert ProSupportReport.objects.get().read_email_sent_at == kwargs.get("read_email_sent_at")

    def test_dry_run(self, django_capture_on_commit_callbacks, mailoutbox):
        report = ProSupportReportFactory(notified_prescriber=PrescriberFactory(), first_read_at=AN_HOUR_AGO)
        CompanyMembershipFactory(company=report.company, user=report.author)

        with django_capture_on_commit_callbacks(execute=True):
            call_command("send_pro_support_report_read_emails")

        assert mailoutbox == []
        report.refresh_from_db()
        assert report.read_email_sent_at is None
