import argparse
from io import BytesIO

import paramiko
from django.db import transaction
from django.utils import timezone
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer

from itou.employee_record import constants
from itou.employee_record.enums import NotificationStatus
from itou.employee_record.models import EmployeeRecord, EmployeeRecordBatch, EmployeeRecordUpdateNotification, Status
from itou.employee_record.serializers import EmployeeRecordSerializer, EmployeeRecordUpdateNotificationSerializer
from itou.utils.command import BaseCommand
from itou.utils.iterators import chunks


class IgnoreFile(Exception):
    def __init__(self, reason):
        self.reason = reason

    def __str__(self):
        return self.reason


class EmployeeRecordTransferCommand(BaseCommand):
    # Limit confirmed by the ASP after sending 50k+ notifications at the same time, which broke things.
    # The file naming scheme also disallows creating more than one file in the same seconds.
    MAX_UPLOADED_FILES = 1

    def add_arguments(self, parser):
        """Subclasses have a preflight option to check for serialization errors."""
        parser.add_argument(
            "--download", dest="download", action="store_true", help="Download employee record processing feedback"
        )
        parser.add_argument(
            "--upload", dest="upload", action="store_true", help="Upload employee records ready for processing"
        )
        parser.add_argument(
            "--parse-file",
            dest="parse_file",
            type=argparse.FileType(mode="rb"),
            help="Parse an employee records feedback file",
        )
        parser.add_argument(
            "--wet-run", dest="wet_run", action="store_true", help="Perform *real* SFTP transfer operations"
        )
        parser.add_argument(
            "--test",
            dest="asp_test",
            action="store_true",
            help="Update employee records with *test* SIRET and financial annex number provided by ASP",
        )
        parser.add_argument(
            "--preflight",
            dest="preflight",
            action="store_true",
            help="Check JSON serialisation of employee records or notifications ready for processing",
        )
        parser.add_argument("--debug", dest="debug", action="store_true")

    def upload_json_file(self, json_data, sftp: paramiko.SFTPClient, dry_run=False) -> str | None:
        """
        Upload `json_data` (as byte array) to given SFTP connection `conn`.
        Returns uploaded filename if ok, `None` otherwise.
        """
        # JSONRenderer produces *byte array* not strings
        json_bytes = JSONRenderer().render(json_data)
        remote_path = f"RIAE_FS_{timezone.now():%Y%m%d%H%M%S}.json"

        if dry_run:
            self.stdout.write(f"DRY-RUN: (not) sending '{remote_path}' ({len(json_bytes)} bytes)")
            self.stdout.write(f"Content: \n{json_bytes}")

            return remote_path

        # Using BytesIO objects allows to use them as files
        # Cool side effect: no temporary file needed
        json_stream = BytesIO(json_bytes)
        # After creating a FileIO object, internal pointer is at the end of the buffer
        # It must be set back to 0 (rewind) otherwise an empty file is sent
        json_stream.seek(0)

        # ASP SFTP server does not return a proper list of transmitted files
        # Whether it's a bug or a paranoid security parameter
        # we must assert that there is no verification of the remote file existence
        # This is the meaning of `confirm=False`
        try:
            sftp.putfo(
                json_stream,
                f"{constants.ASP_FS_REMOTE_UPLOAD_DIR}/{remote_path}",
                file_size=len(json_bytes),
                confirm=False,
            )
        except Exception as ex:
            self.stdout.write(f"Could not upload file: {remote_path}, reason: {ex}")
            return
        self.stdout.write(f"Successfully uploaded: {remote_path}")

        return remote_path

    def _parse_feedback_file(self, feedback_file: str, batch: dict, dry_run: bool) -> int:
        raise NotImplementedError()

    def download_json_file(self, sftp: paramiko.SFTPClient, dry_run: bool):
        self.stdout.write("Starting DOWNLOAD of feedback files")

        # Get into the download folder
        sftp.chdir(constants.ASP_FS_REMOTE_DOWNLOAD_DIR)

        # Get the available feedback files
        result_files = sftp.listdir()

        parser = JSONParser()
        successfully_parsed_files = 0
        for filename in result_files:
            if not filename.startswith("RIAE_FS_"):
                # Remote is shared, so only try to process files related to our management command
                continue

            self.stdout.write(f"Fetching file: {filename}")
            try:
                with sftp.file(filename, mode="r") as result_file, transaction.atomic():
                    # Parse and update employee records with feedback
                    self._parse_feedback_file(filename, parser.parse(result_file), dry_run)
            except IgnoreFile as ex:
                self.stdout.write(f"Ignoring {filename}: {ex}")
                continue
            except Exception as ex:
                self.stdout.write(f"Error while parsing file {filename}: {ex=}")
                self.stdout.write(f"Will not delete file '{filename}' because of errors.")
                continue
            else:
                successfully_parsed_files += 1

            # Everything was fine, we can delete feedback file from server
            self.stdout.write(f"Successfully processed '{filename}', it can be deleted.")
            if not dry_run:
                self.stdout.write(f"Deleting '{filename}' from SFTP server")
                sftp.remove(filename)

        self.stdout.write(f"Successfully parsed {successfully_parsed_files}/{len(result_files)} files")

    def preflight(self, object_class):
        """Parse new notifications or employee records and attempt to tackle serialization errors.
        Serialization of EmployeeRecordBatch objects does not allow detailed information
        on what specific employee record is faulty.
        Doing a precheck will try its best to point precisely to badly formatted objects.
        Important: preflight will crash at the first error encountered (with due details).
        The usual suspect for serialization errors is the obsolete ASP INSEE referential file,
        causing address lookup errors (city, birth city ...) with None values.
        As a reminder, it's a NON-FIX (from both itou and ASP sides), we'll have to deal with it,
        and border it as well as possible."""
        assert object_class in [EmployeeRecord, EmployeeRecordUpdateNotification]

        new_objects = (
            EmployeeRecordUpdateNotification.objects.filter(status=NotificationStatus.NEW)
            if object_class == EmployeeRecordUpdateNotification
            else EmployeeRecord.objects.filter(status=Status.READY)
        )

        object_serializer = (
            EmployeeRecordUpdateNotificationSerializer
            if object_class == EmployeeRecordUpdateNotification
            else EmployeeRecordSerializer
        )

        if not new_objects:
            self.stdout.write("No object to check. Exiting preflight.")
            return

        self.stdout.write(
            f"Found {len(new_objects)} object(s) to check, split in chunks of "
            f"{EmployeeRecordBatch.MAX_EMPLOYEE_RECORDS} objects."
        )

        errors = False
        for idx, elements in enumerate(chunks(new_objects, EmployeeRecordBatch.MAX_EMPLOYEE_RECORDS), 1):
            # A batch + serializer must be created with notifications for correct serialization
            batch = EmployeeRecordBatch(elements)

            self.stdout.write(f"Checking file #{idx} (chunk of {len(elements)} objects)")

            for obj in batch.elements:
                try:
                    object_serializer(obj).data  # Invoke DRF serialization
                except Exception as ex:
                    self.stdout.write(f"ERROR: serialization of {obj} failed!")
                    self.stdout.write("".join(f"> {line}" for line in str(ex).splitlines(keepends=True)))
                    errors = True

        if not errors:
            # Good to go !
            self.stdout.write("All serializations ok, you may skip preflight...")
