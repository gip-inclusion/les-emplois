import datetime
import random
import re

import pytest
from django.core.management import call_command
from django.utils import timezone

from itou.employee_record.enums import NotificationStatus, Status
from itou.employee_record.models import EmployeeRecordBatch
from tests.employee_record import factories


def process_output(caplog_messages):
    assert caplog_messages[-1].startswith(
        "Management command itou.employee_record.management.commands.detect_missing_asp_files succeeded in "
    )
    return [re.sub(r"<EmployeeRecord: .+?>", "[EMPLOYEE RECORD]", msg) for msg in caplog_messages[:-1]]


@pytest.mark.parametrize("with_slack_webhook", [True, False])
def test_nothing_to_report(snapshot, caplog, settings, mocker, with_slack_webhook):
    slack_mock = mocker.patch("itou.employee_record.management.commands.detect_missing_asp_files.send_slack_message")
    if with_slack_webhook:
        settings.SLACK_CRON_WEBHOOK_URL = "http://slack.fake"

    call_command("detect_missing_asp_files")

    assert slack_mock.mock_calls == []
    assert process_output(caplog.messages) == snapshot()


@pytest.mark.parametrize("with_slack_webhook", [True, False])
def test_report(snapshot, caplog, settings, mocker, with_slack_webhook):
    slack_mock = mocker.patch("itou.employee_record.management.commands.detect_missing_asp_files.send_slack_message")
    if with_slack_webhook:
        settings.SLACK_CRON_WEBHOOK_URL = "http://slack.fake"
    old_batch_file_not_sent = EmployeeRecordBatch.REMOTE_PATH_FORMAT.format(
        datetime.datetime(2000, 1, 1, 12, 0, 0).strftime(EmployeeRecordBatch.TIMESTAMP_PATTERN)
    )
    old_batch_file_sent = EmployeeRecordBatch.REMOTE_PATH_FORMAT.format(
        datetime.datetime(2000, 1, 1, 12, 0, 1).strftime(EmployeeRecordBatch.TIMESTAMP_PATTERN)
    )
    old_batch_file_sent_as_update = EmployeeRecordBatch.REMOTE_PATH_FORMAT.format(
        datetime.datetime(2000, 1, 1, 12, 0, 1).strftime(EmployeeRecordBatch.TIMESTAMP_PATTERN)
    )
    recent_batch_file = EmployeeRecordBatch.REMOTE_PATH_FORMAT.format(
        timezone.now().strftime(EmployeeRecordBatch.TIMESTAMP_PATTERN)
    )

    factories.EmployeeRecordFactory(
        status=random.choice([status for status in Status if status != Status.SENT]),
        asp_batch_file=old_batch_file_not_sent,
    )
    factories.EmployeeRecordFactory(status=Status.SENT, asp_batch_file=recent_batch_file)
    factories.EmployeeRecordFactory(status=Status.SENT, asp_batch_file=old_batch_file_sent)

    factories.EmployeeRecordUpdateNotificationFactory(
        status=random.choice([status for status in NotificationStatus if status != NotificationStatus.SENT]),
        asp_batch_file=old_batch_file_not_sent,
    )
    factories.EmployeeRecordUpdateNotificationFactory(
        status=NotificationStatus.SENT,
        asp_batch_file=old_batch_file_sent_as_update,
    )

    call_command("detect_missing_asp_files")
    assert process_output(caplog.messages) == snapshot()
    if with_slack_webhook:
        assert slack_mock.mock_calls == [
            mocker.call(
                text=(
                    "Des fichiers de l'ASP semblent s'être perdus\xa0:\n"
                    " - RIAE_FS_20000101120001.json\xa0: contenant 1 EmployeeRecord\n"
                    " - RIAE_FS_20000101120001.json\xa0: contenant 1 EmployeeRecordUpdateNotification\n\n"
                    "Cf https://app.notion.com/p/gip-inclusion/Fiches-Salari-s-Interconnexion-RIAE-ASP-2415f321b60480c39ff9dfd2078d0c8d"
                ),
                url="http://slack.fake",
            )
        ]
    else:
        assert slack_mock.mock_calls == []
