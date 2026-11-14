from django.template.defaultfilters import pluralize
from django.utils import timezone
from itoutils.django.commands import dry_runnable

from itou.companies.models import ProSupportReport
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    @dry_runnable
    def handle(self, *, wet_run, **options):
        reports = ProSupportReport.objects.filter(
            first_read_at__lte=timezone.now() - ProSupportReport.READ_EMAIL_DELAY,
            read_email_sent_at=None,
            # The prescriber already got in touch with the company.
            introduction_email_sent_at=None,
            company__isnull=False,
            # The prescriber who read the report may have been deleted since.
            notified_prescriber__isnull=False,
        ).select_related("job_seeker", "company", "author", "notified_prescriber")

        sent_reports = []
        for report in reports:
            # Without any admin left, the email waits for auto_attribute_company_admins to appoint one.
            if contact := report.get_company_contact():
                report.notify_read(contact)
                report.read_email_sent_at = timezone.now()
                sent_reports.append(report)
        ProSupportReport.objects.bulk_update(sent_reports, ["read_email_sent_at"])

        s = pluralize(len(sent_reports))
        self.logger.info("Sent read email%s for %d pro support report%s.", s, len(sent_reports), s)
