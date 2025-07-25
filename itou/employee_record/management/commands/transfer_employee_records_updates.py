import paramiko
from django.conf import settings
from django.db import transaction
from rest_framework.parsers import JSONParser
from sentry_sdk.crons import monitor

from itou.employee_record.common_management import EmployeeRecordTransferCommand, IgnoreFile
from itou.employee_record.enums import MovementType, NotificationStatus
from itou.employee_record.exceptions import SerializationError
from itou.employee_record.mocks.fake_serializers import TestEmployeeRecordUpdateNotificationBatchSerializer
from itou.employee_record.models import EmployeeRecordBatch, EmployeeRecordUpdateNotification
from itou.employee_record.serializers import EmployeeRecordUpdateNotificationBatchSerializer
from itou.utils import asp as asp_utils
from itou.utils.iterators import chunks


class Command(EmployeeRecordTransferCommand):
    """
    Manually or automatically:
    - upload approval period updates to ASP servers,
    - download feedback files of previous upload operations,
    """

    def _upload_batch_file(
        self, sftp: paramiko.SFTPClient, notifications: list[EmployeeRecordUpdateNotification], dry_run: bool
    ):
        """
        - render the list of employee record notifications in JSON
        - send it to ASP remote folder.
        """
        raw_batch = EmployeeRecordBatch(notifications)
        # Ability to use ASP test serializers (using fake SIRET numbers)
        if self.asp_test:
            batch_data = TestEmployeeRecordUpdateNotificationBatchSerializer(raw_batch).data
        else:
            batch_data = EmployeeRecordUpdateNotificationBatchSerializer(raw_batch).data

        try:
            # accessing .data triggers serialization
            remote_path = self.upload_json_file(batch_data, sftp, dry_run)
        except SerializationError as ex:
            self.logger.error(
                "Employee records serialization error during upload, can't process.\n"
                "You may want to use --preflight option to check faulty notification objects.\n"
                "Check batch details and error: raw_batch=%s,\nex=%s",
                raw_batch,
                ex,
            )
            return
        except Exception as ex:
            # In any other case, bounce exception
            raise ex from Exception(f"Unhandled error during upload phase for batch: {raw_batch=}")
        else:
            if not remote_path:
                self.logger.warning("Could not upload file, exiting ...")
                return

            # - update employee record notifications status (to SENT)
            # - store in which file they have been seen
            if dry_run:
                self.logger.info("DRY-RUN: Not *really* updating notification statuses")
                return

            for idx, notification in enumerate(notifications, 1):
                notification.wait_for_asp_response(
                    file=remote_path,
                    line_number=idx,
                    archive=batch_data["lignesTelechargement"][idx - 1],
                )

    def _parse_feedback_file(self, feedback_file: str, batch: dict, dry_run: bool) -> None:
        """
        - Parse ASP response file,
        - Update status of employee record notifications,
        - Update metadata for processed employee record notifications.
        """
        batch_filename = EmployeeRecordBatch.batch_filename_from_feedback(feedback_file)

        for idx, employee_record in enumerate(batch["lignesTelechargement"], 1):
            # UPDATE notifications are sent in specific files and are not mixed
            # with "standard" employee records (CREATION).
            if employee_record.get("typeMouvement") != MovementType.UPDATE:
                raise IgnoreFile(f"Received 'typeMouvement' is not {MovementType.UPDATE}")

            line_number = employee_record["numLigne"]
            processing_code = employee_record["codeTraitement"]
            processing_label = employee_record["libelleTraitement"]

            # Pre-check done, now find notification by file name and line number
            notification = EmployeeRecordUpdateNotification.objects.find_by_batch(batch_filename, line_number).first()
            if not notification:
                self.logger.info(
                    f"Skipping, could not get existing employee record notification: {batch_filename=}, {line_number=}"
                )
                # Do not count as an error
                continue
            if notification.status in [NotificationStatus.PROCESSED, NotificationStatus.REJECTED]:
                self.logger.info(f"Skipping, employee record notification is already {notification.status}")
                continue
            if notification.status != NotificationStatus.SENT:
                self.logger.info(f"Skipping, incoherent status for {notification=}")
                continue

            if processing_code == EmployeeRecordUpdateNotification.ASP_PROCESSING_SUCCESS_CODE:  # Processed by ASP
                if not dry_run:
                    notification.process(code=processing_code, label=processing_label, archive=employee_record)
                else:
                    self.logger.info(f"DRY-RUN: Processed {notification}, {processing_code=}, {processing_label=}")
            else:  # Rejected by ASP
                if not dry_run:
                    notification.reject(code=processing_code, label=processing_label, archive=employee_record)
                else:
                    self.logger.info(f"DRY-RUN: Rejected {notification}: {processing_code=}, {processing_label=}")

    @monitor(
        monitor_slug="transfer-employee-records-updates-download",
        monitor_config={
            "schedule": {"type": "crontab", "value": "25 8-18/2 * * MON-FRI"},
            "checkin_margin": 5,
            "max_runtime": 10,
            "failure_issue_threshold": 2,
            "recovery_threshold": 1,
            "timezone": "UTC",
        },
    )
    def download(self, sftp: paramiko.SFTPClient, dry_run: bool):
        """Fetch and process feedback ASP files for employee record notifications"""
        self.download_json_file(sftp, dry_run)

    @monitor(
        monitor_slug="transfer-employee-records-updates-upload",
        monitor_config={
            "schedule": {"type": "crontab", "value": "55 8-18/2 * * MON-FRI"},
            "checkin_margin": 5,
            "max_runtime": 10,
            "failure_issue_threshold": 2,
            "recovery_threshold": 1,
            "timezone": "UTC",
        },
    )
    def upload(self, sftp: paramiko.SFTPClient, dry_run: bool):
        new_notifications = (
            EmployeeRecordUpdateNotification.objects.full_fetch()
            .filter(status=NotificationStatus.NEW)
            .order_by("updated_at", "pk")
        )

        if len(new_notifications) > 0:
            self.logger.info(f"Starting UPLOAD of {len(new_notifications)} notification(s)")
        else:
            self.logger.info("No new employee record notification found")

        for batch in chunks(
            new_notifications, EmployeeRecordBatch.MAX_EMPLOYEE_RECORDS, max_chunk=self.MAX_UPLOADED_FILES
        ):
            self._upload_batch_file(sftp, batch, dry_run)

    def handle(self, *, upload, download, parse_file=None, preflight, wet_run, asp_test=False, debug=False, **options):
        if preflight:
            self.logger.info("Preflight activated, checking for possible serialization errors...")
            self.preflight(EmployeeRecordUpdateNotification)
        elif parse_file:
            # If we need to manually parse a feedback file then we probably have some kind of unexpected state,
            # so use an atomic block to avoid creating more incoherence when something breaks.
            with transaction.atomic():
                self._parse_feedback_file(parse_file.name, JSONParser().parse(parse_file), dry_run=not wet_run)
        elif upload or download:
            if not settings.ASP_SFTP_HOST:
                self.logger.warning("Your environment is missing ASP_SFTP_HOST to run this command.")
                return

            self.asp_test = asp_test
            if asp_test:
                self.logger.info("Using *TEST* JSON serializers (SIRET number mapping)")

            with asp_utils.get_sftp_connection() as sftp:
                self.logger.info(f'Connected to "{settings.ASP_SFTP_HOST}" as "{settings.ASP_SFTP_USER}"')
                self.logger.info(f'''Current remote dir is "{sftp.normalize(".")}"''')

                # Send files to ASP
                if upload:
                    self.upload(sftp, not wet_run)

                # Fetch result files from ASP
                if download:
                    self.download(sftp, not wet_run)

            self.logger.info("Employee record notifications processing done!")
        else:
            self.logger.info("No valid options (upload, download or preflight) were given")
