from itou.users.notifications import ProSupportReportCreatedNotification
from tests.companies.factories import ProSupportReportFactory
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import PrescriberFactory


def test_pro_support_report_created(settings, snapshot):
    settings.PRO_SUPPORT_REPORT_REPLY_TO_EMAIL = "bilans@example.com"
    report = ProSupportReportFactory(
        for_snapshot=True, job_seeker__first_name="Salomé", job_seeker__last_name="Salarié"
    )
    prescriber = PrescriberFactory(for_snapshot=True, membership=False)
    notification = ProSupportReportCreatedNotification(
        prescriber, PrescriberOrganizationFactory(for_snapshot=True), report=report
    )
    email = notification.build()

    assert email.to == [prescriber.email]
    assert email.reply_to == ["bilans@example.com"]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")
    # The job seeker's name is only visible once logged in.
    assert "Salomé" not in email.subject + email.body
    assert "Salarié" not in email.subject + email.body

    settings.PRO_SUPPORT_REPORT_REPLY_TO_EMAIL = None
    assert notification.build().reply_to == []
