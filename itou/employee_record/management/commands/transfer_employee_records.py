import logging
from io import BytesIO

import pysftp
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer
from tqdm import tqdm

from itou.employee_record.models import EmployeeRecord, EmployeeRecordBatch
from itou.employee_record.serializers import EmployeeRecordBatchSerializer
from itou.utils.iterators import chunks


# Global SFTP connection options
cnopts = pysftp.CnOpts()
cnopts.hostkeys = cnopts.hostkeys.load(settings.ASP_FS_KNOWN_HOSTS)

# FIXME
# Temporary mock of some FS fields


def _mock_fs(fs):
    #    ACI 023 20 1111 A0 M0
    pass


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", dest="dry_run", action="store_true", help="Do not perform real SFTP transfer operations"
        )

        parser.add_argument(
            "--download", dest="download", action="store_true", help="Download employee record processing feedback"
        )
        parser.add_argument(
            "--upload", dest="upload", action="store_true", help="Upload employee records ready for processing"
        )

        parser.add_argument("--test", dest="test", action="store_true", help="Send sample file")

    def set_logger(self, verbosity):
        """
        Set logger level based on the verbosity option.
        """
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
        return pysftp.Connection(
            host=settings.ASP_FS_SFTP_HOST,
            port=settings.ASP_FS_SFTP_PORT,
            username=settings.ASP_FS_SFTP_USER,
            private_key=settings.ASP_FS_SFTP_PRIVATE_KEY_PATH,
            cnopts=cnopts,
        )

    def _put_sample_file(self, conn):
        """
        Send a test file

        Will be removed ...
        """
        sample_file = "samples/RIAE_FS_20201113151303.json"

        with conn.cd(settings.ASP_FS_UPLOAD_DIR):
            content = None

            with open(sample_file, "rb") as f:
                content = f.read()
                remote_path = f"RIAE_FS_{timezone.now().strftime('%Y%m%d%H%M%S')}.json"
                conn.putfo(BytesIO(content), remote_path, confirm=False)

                self.logger.info(f"Sent test file: {remote_path}")

    def _get_ready_employee_records(self):
        """
        Get a list of employee records in 'ready' state (ready to be sent)

        Returns a list of list to send several files if needed

        ASP currently accept EmployeeRecordBatch.MAX_EMPLOYEE_RECORDS FS per batch file
        """
        return chunks(EmployeeRecord.objects.ready(), EmployeeRecordBatch.MAX_EMPLOYEE_RECORDS)

    def _put_batch_file(self, conn, employee_records, dry_run=False):
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
            return

        # There are specific folders for upload and download on the SFTP server
        with conn.cd(settings.ASP_FS_UPLOAD_DIR):
            # After creating a FileIO object, internal pointer is a the end of the buffer
            # It must be set back to 0 (rewind) otherwise an empty file is sent
            json_bytes.seek(0)

            # ASP SFTP server does not return a proper list of transmitted files
            # Whether it's a bug or a paranoid security parameter
            # we must assert that there is no verification of the remote file existence
            # This is the meaning `confirm=False`
            try:
                self.logger.info(json_b)
                conn.putfo(json_bytes, remote_path, file_size=len(json_b), confirm=False)
                # with conn.open(remote_path, "w") as remote_file:
                #    remote_file.write(json_s)
                self.logger.info("Succesfully uploaded '%s'", remote_path)
            except Exception as ex:
                self.logger.error("Could not upload file: '%s', reason: %s", remote_path, ex)

    def _update_employee_records_status(self, employe_record):
        pass

    def _get_batch_file(self, conn):
        """
        Fetch ASP processing results

        """
        self.logger.info("Downloading result files...")

        with conn.cd(settings.ASP_FS_DOWNLOAD_DIR):
            result_files = conn.listdir()

            tmp = []
            pbar = tqdm(result_files)

            for result_file in pbar:
                pbar.set_description(f"Fetching '{result_file}'")

                with BytesIO() as result_stream:
                    conn.getfo(result_file, result_stream)
                    result_stream.seek(0)
                    tmp.append(self._process_result_stream(result_stream))

            if len(result_files) == 0:
                self.logger.info("No result files found")
            else:
                self.logger.info("Processed %s files", len(result_files))
                print(tmp)
                # TODO: conn.remove(result_file)
                # Once all ok

    def _process_result_stream(self, result_stream):
        result = JSONParser().parse(result_stream)
        # self.logger.info(result)
        return result

    def handle(self, dry_run=False, upload=True, download=True, test=True, **options):
        self.set_logger(options.get("verbosity"))
        self.logger.info(
            f"Connecting to {settings.ASP_FS_SFTP_USER}@{settings.ASP_FS_SFTP_HOST}:{settings.ASP_FS_SFTP_PORT}"
        )

        both = not (download or upload) and not test

        with self._get_sftp_connection() as sftp:
            self.logger.info(f"Current dir: {sftp.pwd}")

            # Send files
            if both or upload:
                for batch in self._get_ready_employee_records():
                    self._put_batch_file(sftp, batch, dry_run)

            # Fetch result files
            if both or download:
                self._get_batch_file(sftp)

            # Send test file (debug)
            if test:
                self._put_sample_file(sftp)

        print("Done!")
