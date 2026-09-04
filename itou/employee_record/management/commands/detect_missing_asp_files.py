import datetime

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from itou.employee_record.enums import NotificationStatus, Status
from itou.employee_record.models import EmployeeRecord, EmployeeRecordBatch, EmployeeRecordUpdateNotification
from itou.utils.command import BaseCommand
from itou.utils.slack import send_slack_message


# Some files are sent on friday afternoon: the answer is expected on monday morning.
TOO_LONG = datetime.timedelta(days=3)


class Command(BaseCommand):
    """Search for missing files from ASP and send notification to Slack."""

    ATOMIC_HANDLE = False
    AUTO_TRIGGER_CONTEXT = False

    def handle(self, **options):
        self.logger.info("Checking employee records waiting for an ASP response")

        missing_files = []
        for model in [EmployeeRecord, EmployeeRecordUpdateNotification]:
            sent_status = (
                Status.SENT if model == EmployeeRecord else NotificationStatus.SENT
            )  # Yes, this is quite useless
            for filename, er_count in (
                model.objects.filter(status=sent_status)
                .values("asp_batch_file")
                .annotate(Count("pk"))
                .values_list("asp_batch_file", "pk__count")
            ):
                file_sent_at = EmployeeRecordBatch.datetime_from_asp_batch_file(filename)
                if timezone.now() - file_sent_at > TOO_LONG:
                    self.logger.warning(
                        "Found filename=%s for model=%s that seems to have been lost", filename, model.__name__
                    )
                    missing_files.append((model.__name__, filename, er_count))

        if not missing_files:
            self.logger.info("No missing file found")
            return

        if settings.SLACK_CRON_WEBHOOK_URL:
            msg_lines = ["Des fichiers de l'ASP semblent s'être perdus :"]
            for model_name, filename, er_count in missing_files:
                msg_lines.append(f" - {filename} : contenant {er_count} {model_name}")
            msg_lines.append("")
            msg_lines.append(
                "Cf https://app.notion.com/p/gip-inclusion/Fiches-Salari-s-Interconnexion-RIAE-ASP-2415f321b60480c39ff9dfd2078d0c8d"  # noqa: E501
            )

            send_slack_message(
                text="\n".join(msg_lines),
                url=settings.SLACK_CRON_WEBHOOK_URL,
            )
            self.logger.info("Found missing files: %s and notification successfully sent to Slack", missing_files)
        else:
            self.logger.error("Found missing files: %s but no Slack webhook configured", missing_files)
