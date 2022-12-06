from io import BytesIO

import pysftp
from django.conf import settings
from rest_framework.parsers import JSONParser

from itou.employee_record import constants
from itou.employee_record.enums import MovementType, Status
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

    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument(
            "--wet-run", dest="wet_run", action="store_true", help="Perform *real* SFTP transfer operations"
        )
        parser.add_argument(
            "--download", dest="download", action="store_true", help="Download employee record processing feedback"
        )
        parser.add_argument(
            "--upload", dest="upload", action="store_true", help="Upload employee records ready for processing"
        )
        parser.add_argument(
            "--test",
            dest="asp_test",
            action="store_true",
            help="Update employee records with *test* SIRET and financial annex number provided by ASP",
        )

    def _upload_batch_file(
        self, conn: pysftp.Connection, notifications: list[EmployeeRecordUpdateNotification], dry_run: bool
    ):
        """
        - render the list of employee record notifications in JSON
        - send it to ASP remote folder.
        """
        # Ability to use ASP test serializers (using fake SIRET numbers)
        raw_batch = EmployeeRecordBatch(notifications)
        if self.asp_test:
            batch = TestEmployeeRecordUpdateNotificationBatchSerializer(raw_batch)
        else:
            batch = EmployeeRecordUpdateNotificationBatchSerializer(raw_batch)

        try:
            # accessing .data triggers serialization
            remote_path = self.upload_json_file(batch.data, conn, dry_run)
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

            for idx, notification in enumerate(notifications, 1):
                notification.update_as_sent(remote_path, idx)

    def _parse_feedback_file(self, feedback_file: str, batch: dict, dry_run: bool) -> int:
        """
        - parse ASP response file,
        - update status of employee record notifications,
        - return the number of errors encountered.
        """
        batch_filename = EmployeeRecordBatch.batch_filename_from_feedback(feedback_file)
        success_code = "0000"
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
                record_errors += 1
                continue

            # Employee record notification succesfully processed by ASP:
            if processing_code == success_code:
                notification.asp_processing_code = processing_code
                notification.asp_processing_label = processing_label

                if not dry_run:
                    # Not an important issue if notification was previously processed
                    if notification.status != Status.PROCESSED:
                        try:
                            notification.update_as_processed(processing_code, processing_label)
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
                        notification.update_as_rejected(processing_code, processing_label)
                    else:
                        self.stdout.write(f"Already rejected: {notification=}")
                else:
                    self.stdout.write(f"DRY-RUN: Rejected {notification}: {processing_code=}, {processing_label=}")

        return record_errors

    def download(self, conn: pysftp.Connection, dry_run: bool):

        parser = JSONParser()
        count = 0
        total_errors = 0
        files_to_delete = []

        self.stdout.write("Starting DOWNLOAD of employee record notifications")

        with conn.cd(constants.ASP_FS_REMOTE_DOWNLOAD_DIR):
            result_files = conn.listdir()

            if len(result_files) == 0:
                self.stdout.write("No new feedback file found")
                return

            for result_file in result_files:
                # Number of errors per file
                nb_file_errors = 0
                try:
                    with BytesIO() as result_stream:
                        self.stdout.write(f"Fetching file: {result_file}")

                        conn.getfo(result_file, result_stream)
                        result_stream.seek(0)

                        nb_file_errors = self._parse_feedback_file(result_file, parser.parse(result_stream), dry_run)
                        count += 1
                except Exception as ex:
                    nb_file_errors += 1
                    self.stdout.write(f"Error while parsing file {result_file}: {ex=}")

                self.stdout.write(f"Parsed {count}/{len(result_files)} files")

                # There were errors do not delete file
                if nb_file_errors > 0:
                    self.stdout.write(f"Will not delete file '{result_file}' because of errors")
                    total_errors += nb_file_errors
                    continue

                # Everything was fine, will remove file after main loop
                files_to_delete.append(result_file)

            for file in files_to_delete:
                # All employee record notifications processed , we can delete feedback file from server
                if dry_run:
                    self.stdout.write(f"DRY-RUN: Deleting file '{file}'")
                    continue

                self.stdout.write(f"Deleting '{file}' from SFTP server")

                conn.remove(file)

    def upload(self, conn: pysftp.Connection, dry_run: bool):
        new_notifications = EmployeeRecordUpdateNotification.objects.new()

        if len(new_notifications) > 0:
            self.stdout.write(f"Starting UPLOAD of {len(new_notifications)} notification(s)")
        else:
            self.stdout.write("No new employee record notification found")

        for batch in chunks(new_notifications, EmployeeRecordBatch.MAX_EMPLOYEE_RECORDS):
            self._upload_batch_file(conn, batch, dry_run)

    def handle(self, upload=False, download=False, preflight=False, wet_run=False, asp_test=False, **options):
        if not settings.ASP_FS_SFTP_HOST:
            self.stdout.write("Your environment is missing ASP_FS_SFTP_HOST to run this command.")
            return

        dry_run = not wet_run

        self.asp_test = asp_test
        if self.asp_test:
            self.stdout.write("Using *TEST* JSON serializers (SIRET number mapping)")

        if dry_run:
            self.stdout.write("DRY-RUN mode")

        if preflight:
            self.stdout.write("Preflight activated, checking for possible serialization errors...")
            self.preflight(EmployeeRecordUpdateNotification)
            # No other operations are allowed after a preflight
            return

        with self.get_sftp_connection() as sftp:
            user = settings.ASP_FS_SFTP_USER or "django_tests"
            self.stdout.write(f"Connected to: {user}@{settings.ASP_FS_SFTP_HOST}")
            self.stdout.write(f"Current remote dir is: {sftp.pwd}")

            # Send files to ASP
            if upload:
                self.upload(sftp, dry_run)

            # Fetch result files from ASP
            if download:
                self.download(sftp, dry_run)

        self.stdout.write("Employee record notifications processing done!")
