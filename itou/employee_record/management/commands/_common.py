from io import BytesIO
from os import path
from typing import Optional

import pysftp
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from rest_framework.renderers import JSONRenderer


# Global SFTP connection options

connection_options = None

if settings.ASP_FS_KNOWN_HOSTS and path.exists(settings.ASP_FS_KNOWN_HOSTS):
    connection_options = pysftp.CnOpts(knownhosts=settings.ASP_FS_KNOWN_HOSTS)


class EmployeeRecordTransferCommand(BaseCommand):
    def get_sftp_connection(self) -> pysftp.Connection:
        """
        Get a new SFTP connection to remote server.
        """
        return pysftp.Connection(
            host=settings.ASP_FS_SFTP_HOST,
            port=int(settings.ASP_FS_SFTP_PORT),
            username=settings.ASP_FS_SFTP_USER,
            private_key=settings.ASP_FS_SFTP_PRIVATE_KEY_PATH,
            cnopts=connection_options,
        )

    def upload_json_file(self, json_data, conn: pysftp.Connection, dry_run=False) -> Optional[str]:
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
        with conn.cd(settings.ASP_FS_REMOTE_UPLOAD_DIR):
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
