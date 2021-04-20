import logging
from io import BytesIO
from os import path

import pysftp
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer

from itou.employee_record.models import EmployeeRecord, EmployeeRecordBatch
from itou.employee_record.serializers import EmployeeRecordBatchSerializer, EmployeeRecordSerializer
from itou.utils.iterators import chunks


# Global SFTP connection options

cnopts = None

if settings.ASP_FS_KNOWN_HOSTS and path.exists(settings.ASP_FS_KNOWN_HOSTS):
    cnopts = pysftp.CnOpts()
    cnopts.hostkeys = cnopts.hostkeys.load(settings.ASP_FS_KNOWN_HOSTS)


class Command(BaseCommand):
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
        parser.add_argument(
            "--dry-run", dest="dry_run", action="store_true", help="Do not perform real SFTP transfer operations"
        )
        parser.add_argument(
            "--download", dest="download", action="store_true", help="Download employee record processing feedback"
        )
        parser.add_argument(
            "--upload", dest="upload", action="store_true", help="Upload employee records ready for processing"
        )

    def set_logger(self, verbosity):
        """
        Set logger level based on the verbosity option.
        """
        if hasattr(self, "logger"):
            return

        handler = logging.StreamHandler(self.stdout)

        self.logger = logging.getLogger(__name__)
        self.logger.propagate = False
        self.logger.addHandler(handler)

        self.logger.setLevel(logging.INFO)
        if verbosity > 1:
            self.logger.setLevel(logging.DEBUG)

    def log(self, message):
        self.logger.debug(message)

    def _get_sftp_connection(self):
        """
        Get a new SFTP connection to remote server
        """
        return pysftp.Connection(
            host=settings.ASP_FS_SFTP_HOST,
            port=settings.ASP_FS_SFTP_PORT,
            username=settings.ASP_FS_SFTP_USER,
            private_key=settings.ASP_FS_SFTP_PRIVATE_KEY_PATH,
            cnopts=cnopts,
        )

    def _store_processing_report(self, conn, remote_path, content, local_path=settings.ASP_FS_DOWNLOAD_DIR):
        """
        Store ASP processing results in a local file

        Content is a string
        """
        with open(f"{local_path}/{remote_path}", "w") as f:
            f.write(content)
        self.logger.info("Wrote '%s' to local path '%s'", remote_path, local_path)

    def _upload_batch_file(self, conn, employee_records, dry_run):
        """
        Render a list of employee records in JSON format then send it to SFTP upload folder
        """
        batch = EmployeeRecordBatchSerializer(EmployeeRecordBatch(employee_records))

        # JSONRenderer produces byte arrays
        json_b = JSONRenderer().render(batch.data)

        # Using FileIO objects allows to use them as files
        # Cool side effect: no temporary file needed
        json_bytes = BytesIO(json_b)
        remote_path = f"RIAE_FS_{timezone.now().strftime('%Y%m%d%H%M%S')}.json"

        if dry_run:
            self.logger.info("DRY-RUN: (not) sending '%s' (%d bytes)", remote_path, len(json_b))
            self.logger.info("Content: \n%s", json_b)
            return

        # There are specific folders for upload and download on the SFTP server
        with conn.cd(settings.ASP_FS_UPLOAD_DIR):
            # After creating a FileIO object, internal pointer is at the end of the buffer
            # It must be set back to 0 (rewind) otherwise an empty file is sent
            json_bytes.seek(0)

            # ASP SFTP server does not return a proper list of transmitted files
            # Whether it's a bug or a paranoid security parameter
            # we must assert that there is no verification of the remote file existence
            # This is the meaning of `confirm=False`
            try:
                conn.putfo(json_bytes, remote_path, file_size=len(json_b), confirm=False)

                self.logger.info("Succesfully uploaded '%s'", remote_path)
            except Exception as ex:
                self.logger.error("Could not upload file: '%s', reason: %s", remote_path, ex)

                return

            # Now that file is transfered, update employee records status (SENT)
            # and store in which file they have been sent
            for idx, employee_record in enumerate(employee_records, 1):
                employee_record.sent_in_asp_batch_file(remote_path, idx)

    def _parse_feedback_file(self, feedback_file, batch, dry_run):
        """
        - Parse ASP response file,
        - Update status of employee records,
        - Update metadata for processed employee records.

        Returns the number of errors encountered
        """
        batch_filename = EmployeeRecordBatch.batch_filename_from_feedback(feedback_file)
        renderer = JSONRenderer()
        success_code = "0000"
        record_errors = 0

        records = batch.get("lignesTelechargement")

        if not records:
            self.logger.error("Could not get any employee record from file: %s", feedback_file)

            return 1

        for idx, employee_record in enumerate(records, 1):
            line_number = employee_record.get("numLigne")
            processing_code = employee_record.get("codeTraitement")
            processing_label = employee_record.get("libelleTraitement")

            self.logger.debug("Line number: %s", line_number)
            self.logger.debug("Processing code: %s", processing_code)
            self.logger.debug("Processing label: %s", processing_label)

            if not line_number:
                self.logger.warning("No line number for employee record (index: %s, file: %s)", idx, feedback_file)
                continue

            # Now we must find the matching FS
            employee_record = EmployeeRecord.objects.find_by_batch(batch_filename, line_number).first()

            if not employee_record:
                self.logger.error(
                    "Could not get existing employee record data: BATCH_FILE=%s, LINE_NUMBER=%s",
                    batch_filename,
                    line_number,
                )
                record_errors += 1
                continue

            if processing_code == success_code:
                # Archive JSON copy of employee record (with processing code and label)
                serializer = EmployeeRecordSerializer(employee_record)
                if not dry_run:
                    employee_record.accepted_by_asp(
                        processing_code, processing_label, renderer.render(serializer.data).decode()
                    )
                else:
                    self.logger.info("DRY-RUN: accepted %s", employee_record)
                continue

            if not dry_run:
                employee_record.rejected_by_asp(processing_code, processing_label)
            else:
                self.logger.info(
                    "DRY-RUN: rejected %s, code: %s, label: %s", employee_record, processing_code, processing_label
                )

        return record_errors

    def download(self, conn, dry_run):
        """
        Fetch remote ASP file containing the results of the processing
        of a batch of employee records
        """
        parser = JSONParser()
        count = 0
        errors = 0

        # Get into the download folder
        with conn.cd(settings.ASP_FS_DOWNLOAD_DIR):
            result_files = conn.listdir()

            if len(result_files) == 0:
                self.logger.info("No feedback files found")
                return

            for result_file in result_files:
                try:
                    with BytesIO() as result_stream:
                        self.logger.info("Fetching file '%s'", result_file)

                        conn.getfo(result_file, result_stream)
                        # Rewind stream
                        result_stream.seek(0)

                        # Parse and update employee records with feedback
                        errors += self._parse_feedback_file(result_file, parser.parse(result_stream), dry_run)

                        count += 1
                except Exception as ex:
                    errors += 1
                    self.logger.error("Error while parsing file '%s': %s", result_file, ex)

                self.logger.info("Parsed %s/%s files", count, len(result_files))

            # There were errors do not delete file
            if errors > 0:
                self.logger.warning(
                    "Did not delete file '%s' because of errors. Leaving it in place for another pass...", result_file
                )
                return

            # All employee records processed, we can delete feedback file from server
            self.logger.info("Deleting '%s' from SFTP server", result_file)
            conn.remove(result_file)

    def upload(self, sftp, dry_run):
        """
        Upload a file composed of all ready employee records
        """
        for batch in chunks(EmployeeRecord.objects.ready(), EmployeeRecordBatch.MAX_EMPLOYEE_RECORDS):
            self._upload_batch_file(sftp, batch, dry_run)

    def handle(self, upload=True, download=True, verbosity=1, dry_run=False, **options):
        """
        Employee Record Management Command
        """

        self.set_logger(verbosity)
        both = not (download or upload)

        with self._get_sftp_connection() as sftp:
            user = settings.ASP_FS_SFTP_USER or "django_tests"
            self.logger.info(f"Connected to {user}@{settings.ASP_FS_SFTP_HOST}:{settings.ASP_FS_SFTP_PORT}")
            self.logger.info(f"Current dir: {sftp.pwd}")

            # Send files
            if both or upload:
                self.upload(sftp, dry_run)

            # Fetch results from ASP
            if both or download:
                self.download(sftp, dry_run)

        self.logger.info("Employee records processing done!")
