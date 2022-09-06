from io import BytesIO

from django.conf import settings
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer

from itou.employee_record.enums import MovementType, Status
from itou.employee_record.exceptions import SerializationError
from itou.employee_record.mocks.test_serializers import TestEmployeeRecordBatchSerializer
from itou.employee_record.models import EmployeeRecord, EmployeeRecordBatch
from itou.employee_record.serializers import EmployeeRecordBatchSerializer, EmployeeRecordSerializer
from itou.utils.iterators import chunks

from .common import EmployeeRecordTransferCommand


class Command(EmployeeRecordTransferCommand):
    """
    Employee record management command
    ---
    Allow to manually or automatically:
    - upload ready to be processed employee records
    - download feedback files of previous upload operations
    - perform dry-run operations
    """

    def add_arguments(self, parser):
        """
        Command line arguments
        """
        super().add_arguments(parser)

        parser.add_argument(
            "--dry-run", dest="dry_run", action="store_true", help="Do not perform real SFTP transfer operations"
        )
        parser.add_argument(
            "--download", dest="download", action="store_true", help="Download employee record processing feedback"
        )
        parser.add_argument(
            "--upload", dest="upload", action="store_true", help="Upload employee records ready for processing"
        )
        parser.add_argument(
            "--archive", dest="archive", action="store_true", help="Archive old processed employee records"
        )
        parser.add_argument(
            "--test",
            dest="asp_test",
            action="store_true",
            help="Update employee records with test SIRET and financial annex number",
        )

    def _upload_batch_file(self, conn, employee_records, dry_run):
        """
        Render a list of employee records in JSON format then send it to SFTP upload folder
        """
        # Temporary ability to use test serializers
        raw_batch = EmployeeRecordBatch(employee_records)
        batch = (
            TestEmployeeRecordBatchSerializer(raw_batch) if self.asp_test else EmployeeRecordBatchSerializer(raw_batch)
        )

        try:
            remote_path = self.upload_json_file(batch.data, conn, dry_run)
        except SerializationError as ex:
            self.stdout.write(
                f"Employee records serialization error during upload, can't process.\n"
                f"You may want to use --preflight option to check faulty employee record objects.\n"
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
                self.stdout.write("DRY-RUN: Not *really* updating employee records statuses")
                return

            # Now that file is transfered, update employee records status (SENT)
            # and store in which file they have been sent
            for idx, employee_record in enumerate(employee_records, 1):
                employee_record.update_as_sent(remote_path, idx)

    def _parse_feedback_file(self, feedback_file, batch, dry_run) -> int:
        """
        - Parse ASP response file,
        - Update status of employee records,
        - Update metadata for processed employee records.

        Returns the number of errors encountered
        """
        batch_filename = EmployeeRecordBatch.batch_filename_from_feedback(feedback_file)
        renderer = JSONRenderer()
        record_errors = 0
        records = batch.get("lignesTelechargement")

        if not records:
            self.stdout.write(f"Could not get any employee record from file: {feedback_file}")
            return 1

        # Check for notification records :
        # Notifications are not mixed with employee records
        notification_number = 0

        for record in records:
            if record.get("typeMouvement") == MovementType.UPDATE:
                notification_number += 1

        if notification_number == len(records):
            self.stdout.write(
                f"File `{feedback_file}` is an update notifications file, passing.",
            )
            return 1

        for idx, employee_record in enumerate(records, 1):
            line_number = employee_record.get("numLigne")
            processing_code = employee_record.get("codeTraitement")
            processing_label = employee_record.get("libelleTraitement")

            self.stdout.write(f"Record: {line_number=}, {processing_code=}, {processing_label=}")

            if not line_number:
                self.stdout.write(f"No line number for employee record {idx=}, {feedback_file=}", idx, feedback_file)
                continue

            # Now we must find the matching FS
            employee_record = EmployeeRecord.objects.find_by_batch(batch_filename, line_number).first()

            if not employee_record:
                self.stdout.write(f"Could not get existing employee record data: {batch_filename=}, {line_number=}")
                # Do not count as an error
                continue

            # Employee record succesfully processed by ASP :
            if processing_code == EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE:
                # Archive a JSON copy of employee record (with processing code and label)
                employee_record.asp_processing_code = processing_code
                employee_record.asp_processing_label = processing_label

                serializer = EmployeeRecordSerializer(employee_record)

                if not dry_run:
                    try:
                        if employee_record.status != Status.PROCESSED:
                            employee_record.update_as_processed(
                                processing_code, processing_label, renderer.render(serializer.data).decode()
                            )
                        else:
                            self.stdout.write(f"Already accepted: {employee_record=}")
                    except Exception as ex:
                        self.stdout.write(
                            f"Can't update employee record : {employee_record=} {employee_record.status=} {ex=}"
                        )
                else:
                    self.stdout.write(f"DRY-RUN: Accepted {employee_record=}, {processing_code=}, {processing_label=}")
            else:
                # Employee record has already been processed : SKIP, not an error
                if employee_record.status == Status.PROCESSED:
                    # Do not update, keep it clean
                    self.stdout.write(f"Skipping, already accepted: {employee_record=}")
                    continue

                # Employee record has not been processed by ASP :
                if not dry_run:
                    # One special case added for support concerns:
                    # 3436 processing code are automatically converted as PROCESSED
                    if processing_code == EmployeeRecord.ASP_DUPLICATE_ERROR_CODE:
                        employee_record.status = Status.REJECTED
                        employee_record.asp_processing_code = EmployeeRecord.ASP_DUPLICATE_ERROR_CODE
                        employee_record.update_as_processed_as_duplicate()
                        continue

                    # Fixes unexpected stop on multiple pass on the same file
                    if employee_record.status != Status.REJECTED:
                        # Standard error / rejection processing
                        employee_record.update_as_rejected(processing_code, processing_label)
                    else:
                        self.stdout.write(f"Already rejected: {employee_record=}")
                else:
                    self.stdout.write(f"DRY-RUN: Rejected {employee_record=}, {processing_code=}, {processing_label=}")

        return record_errors

    def download(self, conn, dry_run):
        """
        Fetch remote ASP file containing the results of the processing
        of a batch of employee records
        """
        self.stdout.write("Starting DOWNLOAD of employee records")

        parser = JSONParser()
        count = 0
        total_errors = 0
        files_to_delete = []

        # Get into the download folder
        with conn.cd(settings.ASP_FS_REMOTE_DOWNLOAD_DIR):
            result_files = conn.listdir()

            if len(result_files) == 0:
                self.stdout.write("No feedback files found")
                return

            for result_file in result_files:
                # Number of errors per file
                nb_file_errors = 0
                try:
                    with BytesIO() as result_stream:
                        self.stdout.write(f"Fetching file: {result_file=}")

                        conn.getfo(result_file, result_stream)
                        # Rewind stream
                        result_stream.seek(0)

                        # Parse and update employee records with feedback
                        nb_file_errors = self._parse_feedback_file(result_file, parser.parse(result_stream), dry_run)

                        count += 1
                except Exception as ex:
                    nb_file_errors += 1
                    self.stdout.write(f"Error while parsing file {result_file=}, {ex=}")

                self.stdout.write(f"Parsed {count}/{len(result_files)} files")

                # There were errors: do not delete file
                if nb_file_errors > 0:
                    self.stdout.write(f"Will not delete file '{result_file}' because of errors.")
                    total_errors += nb_file_errors
                    continue

                # Everything was fine, will remove file after main loop
                files_to_delete.append(result_file)

            for file in files_to_delete:
                # All employee records processed, we can delete feedback file from server
                if dry_run:
                    self.stdout.write(f"DRY-RUN: Removing file '{file}'")
                    continue

                self.stdout.write(f"Deleting '{file}' from SFTP server")

                conn.remove(file)

    def upload(self, sftp, dry_run):
        """
        Upload a file composed of all ready employee records
        """
        ready_employee_records = EmployeeRecord.objects.ready()

        # FIXME: temp disabled, too much impact, must be discussed
        # As requested by ASP, we can now send employee records in bigger batches
        # if len(ready_employee_records) < EmployeeRecordBatch.MAX_EMPLOYEE_RECORDS:
        #     self.logger.info(
        #         "Not enough employee records to initiate a transfer (%s / %s)",
        #        len(ready_employee_records),
        #         EmployeeRecordBatch.MAX_EMPLOYEE_RECORDS,
        #     )
        #     return

        self.stdout.write("Starting UPLOAD of employee records")

        for batch in chunks(ready_employee_records, EmployeeRecordBatch.MAX_EMPLOYEE_RECORDS):
            self._upload_batch_file(sftp, batch, dry_run)

    def archive(self, dry_run):
        """
        Archive old employee record data:
        records are not deleted but their `archived_json` field is erased if employee record has been
        in `PROCESSED` status for more than EMPLOYEE_RECORD_ARCHIVING_DELAY_IN_DAYS days
        """
        self.stdout.write(
            f"Archiving employee records (more than {settings.EMPLOYEE_RECORD_ARCHIVING_DELAY_IN_DAYS} days old)"
        )
        archivable = EmployeeRecord.objects.archivable()

        if (cnt := archivable.count()) > 0:
            self.stdout.write(f"Found {cnt} archivable employee record(s)")
            if dry_run:
                return
            archived_cnt = 0

            # A bulk update will increase performance if there are a lot of employee records to update.
            # However, if there is no performance issue, it is preferable to keep the archiving
            # and validation logic in the model (update_as_archived).
            # Update: let's bulk, with a batch size of 100 records
            for er in archivable:
                try:
                    # Do not trigger a save() call on the object
                    er.update_as_archived(save=False)
                    archived_cnt += 1
                except Exception as ex:
                    self.stdout.write(f"Can't archive record {er=} {ex=}")

            # Bulk update (100 records block):
            EmployeeRecord.objects.bulk_update(archivable, ["status", "updated_at", "archived_json"], batch_size=100)

            self.stdout.write(f"Archived {archived_cnt}/{cnt} employee record(s)")
        else:
            self.stdout.write("No archivable employee record found, exiting.")

    def handle(
        self,
        upload=True,
        download=True,
        preflight=False,
        dry_run=False,
        asp_test=False,
        archive=False,
        **_,
    ):
        if not settings.EMPLOYEE_RECORD_TRANSFER_ENABLED:
            self.stdout.write(
                "This management command can't be used in this environment. Update Django settings if needed."
            )
            # Goodbye Marylou
            return

        if preflight:
            self.stdout.write("Preflight activated, checking for possible serialization errors...")
            self.preflight(EmployeeRecord)
            # No other operations are allowed after a preflight
            return

        self.asp_test = asp_test

        if self.asp_test:
            self.stdout.write("Using *TEST* JSON serializers (SIRET number mapping)")

        with self.get_sftp_connection() as sftp:
            user = settings.ASP_FS_SFTP_USER or "django_tests"
            self.stdout.write(f"Connected to {user}@{settings.ASP_FS_SFTP_HOST}:{settings.ASP_FS_SFTP_PORT}")
            self.stdout.write(f"Current dir: {sftp.pwd}")

            # Send files
            if upload:
                self.upload(sftp, dry_run)

            # Fetch results from ASP
            if download:
                self.download(sftp, dry_run)

        if archive:
            self.archive(dry_run)

        self.stdout.write("Employee records processing done")
