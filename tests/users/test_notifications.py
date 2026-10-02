from django.conf import settings

from itou.users.notifications import ProSupportReportCreatedNotification
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import PrescriberFactory, ProSupportReportFactory


def test_pro_support_report_created(snapshot):
    report = ProSupportReportFactory(
        for_snapshot=True, job_seeker__first_name="Salomé", job_seeker__last_name="Salarié"
    )
    prescriber = PrescriberFactory(for_snapshot=True, membership=False)
    email = ProSupportReportCreatedNotification(
        prescriber, PrescriberOrganizationFactory(for_snapshot=True), report=report
    ).build()

    assert email.to == [prescriber.email]
    assert email.reply_to == [settings.PRO_SUPPORT_REPORT_REPLY_TO_EMAIL]
    assert email.subject == snapshot(name="subject")
    assert email.body == snapshot(name="body")
    # The job seeker's name is only visible once logged in.
    assert "Salomé" not in email.subject + email.body
    assert "Salarié" not in email.subject + email.body
