import paramiko
from django.conf import settings
from django.db import transaction
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer
from sentry_sdk.crons import monitor

from itou.employee_record.enums import MovementType, NotificationStatus, Status
from itou.employee_record.exceptions import SerializationError
from itou.employee_record.mocks.fake_serializers import TestEmployeeRecordUpdateNotificationBatchSerializer
from itou.employee_record.models import EmployeeRecordBatch, EmployeeRecordUpdateNotification
from itou.employee_record.serializers import EmployeeRecordUpdateNotificationBatchSerializer
from itou.utils.iterators import chunks

from ...common_management import EmployeeRecordTransferCommand


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
            self.stdout.write(
                f"Employee records serialization error during upload, can't process.\n"
                f"You may want to use --preflight option to check faulty notification objects.\n"
                f"Check batch details and error: {raw_batch=},\n{ex=}"
            )
            return
        except Exception as ex:
            # In any other case, bounce exception
            raise ex from Exception(f"Unhandled error during upload phase for batch: {raw_batch=}")
        else:
            if not remote_path:
                self.stdout.write("Could not upload file, exiting ...")
                return

            # - update employee record notifications status (to SENT)
            # - store in which file they have been seen
            if dry_run:
                self.stdout.write("DRY-RUN: Not *really* updating notification statuses")
                return

            renderer = JSONRenderer()
            for idx, notification in enumerate(notifications, 1):
                notification.update_as_sent(
                    remote_path, idx, renderer.render(batch_data["lignesTelechargement"][idx - 1])
                )

    def _parse_feedback_file(self, feedback_file: str, batch: dict, dry_run: bool) -> int:
        """
        - parse ASP response file,
        - update status of employee record notifications,
        - return the number of errors encountered.
        """
        batch_filename = EmployeeRecordBatch.batch_filename_from_feedback(feedback_file)
        record_errors = 0
        records = batch.get("lignesTelechargement")

        if not records:
            self.stdout.write(f"Could not get any employee record notification from file: {feedback_file=}")
            return 0

        for idx, employee_record in enumerate(records, 1):
            if employee_record.get("typeMouvement") != MovementType.UPDATE:
                # Update notifications are sent in specific files and are not mixed
                # with "standard" employee records (CREATE mode).
                # If CREATE movements are found in this file, we must skip it.
                self.stdout.write(f"This feedback file is not a notification update file: SKIPPING, {feedback_file=}")
                # This will be marked as an error, stop loop and return
                return 1

            line_number = employee_record.get("numLigne")
            processing_code = employee_record.get("codeTraitement")
            processing_label = employee_record.get("libelleTraitement")

            if not line_number:
                self.stdout.write(f"No line number for employee record ({idx=}, {feedback_file=})")
                record_errors += 1
                continue

            # Pre-check done, now find notification by file name and line number
            notification = EmployeeRecordUpdateNotification.objects.find_by_batch(batch_filename, line_number).first()

            if not notification:
                self.stdout.write(f"Could not get existing notification: {batch_filename=}, {line_number=}")
                # Do not count as an error
                continue

            archived_json = JSONRenderer().render(employee_record)
            # Employee record notification successfully processed by ASP:
            if processing_code == EmployeeRecordUpdateNotification.ASP_PROCESSING_SUCCESS_CODE:
                if not dry_run:
                    # Not an important issue if notification was previously processed
                    if notification.status != Status.PROCESSED:
                        try:
                            notification.update_as_processed(processing_code, processing_label, archived_json)
                        except Exception as ex:
                            record_errors += 1
                            self.stdout.write(f"Can't perform update: {notification=}, {ex=}")
                else:
                    self.stdout.write(f"DRY-RUN: Processed {notification}, {processing_code=}, {processing_label=}")
            else:
                # Employee record is REJECTED:
                if not dry_run:
                    # Fix unexpected stop on multiple pass on the same file
                    if notification.status != Status.REJECTED:
                        notification.update_as_rejected(processing_code, processing_label, archived_json)
                    else:
                        self.stdout.write(f"Already rejected: {notification=}")
                else:
                    self.stdout.write(f"DRY-RUN: Rejected {notification}: {processing_code=}, {processing_label=}")

        return record_errors

    @monitor(monitor_slug="transfer-employee-records-updates-download")
    def download(self, sftp: paramiko.SFTPClient, dry_run: bool):
        """Fetch and process feedback ASP files for employee record notifications"""
        self.download_json_file(sftp, dry_run)

    @monitor(monitor_slug="transfer-employee-records-updates-upload")
    def upload(self, sftp: paramiko.SFTPClient, dry_run: bool):
        new_notifications = EmployeeRecordUpdateNotification.objects.filter(status=NotificationStatus.NEW)

        if len(new_notifications) > 0:
            self.stdout.write(f"Starting UPLOAD of {len(new_notifications)} notification(s)")
        else:
            self.stdout.write("No new employee record notification found")

        for batch in chunks(
            new_notifications, EmployeeRecordBatch.MAX_EMPLOYEE_RECORDS, max_chunk=self.MAX_UPLOADED_FILES
        ):
            self._upload_batch_file(sftp, batch, dry_run)

    def handle(self, *, upload, download, parse_file=None, preflight, wet_run, asp_test=False, debug=False, **options):
        if preflight:
            self.stdout.write("Preflight activated, checking for possible serialization errors...")
            self.preflight(EmployeeRecordUpdateNotification)
        elif parse_file:
            # If we need to manually parse a feedback file then we probably have some kind of unexpected state,
            # so use an atomic block to avoid creating more incoherence when something breaks.
            with transaction.atomic():
                self._parse_feedback_file(parse_file.name, JSONParser().parse(parse_file), dry_run=not wet_run)
        elif upload or download:
            if not settings.ASP_FS_SFTP_HOST:
                self.stdout.write("Your environment is missing ASP_FS_SFTP_HOST to run this command.")
                return

            self.asp_test = asp_test
            if asp_test:
                self.stdout.write("Using *TEST* JSON serializers (SIRET number mapping)")

            with self.get_sftp_connection(debug=debug) as sftp:
                self.stdout.write(f'Connected to "{settings.ASP_FS_SFTP_HOST}" as "{settings.ASP_FS_SFTP_USER}"')
                self.stdout.write(f'''Current remote dir is "{sftp.normalize('.')}"''')

                # Send files to ASP
                if upload:
                    self.upload(sftp, not wet_run)

                # Fetch result files from ASP
                if download:
                    self.download(sftp, not wet_run)

            self.stdout.write("Employee record notifications processing done!")
        else:
            self.stdout.write("No valid options (upload, download or preflight) were given")
