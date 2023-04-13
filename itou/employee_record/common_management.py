from io import BytesIO
from os import path

import pysftp
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from rest_framework.renderers import JSONRenderer

from itou.employee_record import constants
from itou.employee_record.enums import NotificationStatus
from itou.employee_record.exceptions import SerializationError
from itou.employee_record.models import EmployeeRecord, EmployeeRecordBatch, EmployeeRecordUpdateNotification, Status
from itou.employee_record.serializers import EmployeeRecordSerializer, EmployeeRecordUpdateNotificationSerializer
from itou.utils.iterators import chunks


# Global SFTP connection options

connection_options = None

if settings.ASP_FS_KNOWN_HOSTS and path.exists(settings.ASP_FS_KNOWN_HOSTS):
    connection_options = pysftp.CnOpts(knownhosts=settings.ASP_FS_KNOWN_HOSTS)


class EmployeeRecordTransferCommand(BaseCommand):
    def add_arguments(self, parser):
        """Subclasses have a preflight option to check for serialization errors."""
        parser.add_argument(
            "--preflight",
            dest="preflight",
            action="store_true",
            help="Check JSON serialisation of employee records or notifications ready for processing",
        )

    def get_sftp_connection(self) -> pysftp.Connection:
        """
        Get a new SFTP connection to remote server.
        """
        return pysftp.Connection(
            host=settings.ASP_FS_SFTP_HOST,
            port=settings.ASP_FS_SFTP_PORT,  # default setting is None, pysftp would then default to 22
            username=settings.ASP_FS_SFTP_USER,
            private_key=settings.ASP_FS_SFTP_PRIVATE_KEY_PATH,
            cnopts=connection_options,
        )

    def upload_json_file(self, json_data, conn: pysftp.Connection, dry_run=False) -> str | None:
        """
        Upload `json_data` (as byte array) to given SFTP connection `conn`.
        Returns uploaded filename if ok, `None` otherwise.
        """
        # JSONRenderer produces *byte array* not strings
        json_bytes = JSONRenderer().render(json_data)
        now = timezone.now()

        # Using FileIO objects allows to use them as files
        # Cool side effect: no temporary file needed
        json_stream = BytesIO(json_bytes)
        remote_path = f"RIAE_FS_{now:%Y%m%d%H%M%S}.json"

        if dry_run:
            self.stdout.write(f"DRY-RUN: (not) sending '{remote_path}' ({len(json_bytes)} bytes)")
            self.stdout.write(f"Content: \n{json_bytes}")

            return remote_path

        # There are specific folders for upload and download on the SFTP server
        with conn.cd(constants.ASP_FS_REMOTE_UPLOAD_DIR):
            # After creating a FileIO object, internal pointer is at the end of the buffer
            # It must be set back to 0 (rewind) otherwise an empty file is sent
            json_stream.seek(0)

            # ASP SFTP server does not return a proper list of transmitted files
            # Whether it's a bug or a paranoid security parameter
            # we must assert that there is no verification of the remote file existence
            # This is the meaning of `confirm=False`
            try:
                conn.putfo(json_stream, remote_path, file_size=len(json_bytes), confirm=False)

                self.stdout.write(f"Successfully uploaded: {remote_path}")
            except Exception as ex:
                self.stdout.write(f"Could not upload file: {remote_path}, reason: {ex}")
                return

        return remote_path

    def download_json_file(self):
        # FIXME
        pass

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

        for idx, elements in enumerate(chunks(new_objects, EmployeeRecordBatch.MAX_EMPLOYEE_RECORDS), 1):
            # A batch + serializer must be created with notifications for correct serialization
            batch = EmployeeRecordBatch(elements)

            self.stdout.write(f"Checking file #{idx} (chunk of {len(elements)} objects)")

            for obj in batch.elements:
                ser = object_serializer(obj)
                try:
                    ser.data  # Invoke DRF serialization
                except Exception as secondary_ex:
                    # Attach cause exception for more details
                    raise SerializationError(f"JSON serialization of {obj=} failed.") from secondary_ex

        # Good to go !
        self.stdout.write("All serializations ok, you may skip preflight...")
