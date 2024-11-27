"""
The FluxIAE file contains data used by les emplois and is uploaded to us directly by a supporting organization.
The same file is also parsed by the Pilotage, shared via an S3 bucket.

This command uploads the file from where it has been stored to the S3 bucket for sharing.
"""

import pathlib
import threading
from pathlib import Path

from django.conf import settings
from django.template.defaultfilters import filesizeformat

from itou.utils.command import BaseCommand
from itou.utils.storage.s3 import pilotage_s3_client


class Command(BaseCommand):
    help = "Upload FluxIAE to S3 for sharing."

    FILENAME_PREFIX = "fluxIAE_ITOU_"
    DATASTORE_DIRECTORY = "flux-iae/"

    def add_arguments(self, parser):
        parser.add_argument("directory", type=Path, help="Directory containing FluxIAE files")
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    def _upload_file(self, file: pathlib.Path, *, wet_run=False):
        lock = threading.Lock()
        file_size = file.stat().st_size
        bytes_transferred = 0
        previous_progress = 0

        def log_progress(chunk_size):
            """Logs to console or logs the progress of byte transfer"""
            nonlocal bytes_transferred
            nonlocal previous_progress

            with lock:
                bytes_transferred += chunk_size
                progress = int((bytes_transferred / file_size) * 100)
                if progress > previous_progress and progress % 5 == 0:
                    self.stdout.write(
                        f"> {file.name}: {filesizeformat(bytes_transferred)}/{filesizeformat(file_size)} transferred ({progress}%)."  # noqa: E501
                    )
                    previous_progress = progress

        if wet_run:
            pilotage_s3_client().upload_file(
                Filename=file.absolute(),
                Bucket=settings.PILOTAGE_DATASTORE_S3_BUCKET_NAME,
                Key=f"{self.DATASTORE_DIRECTORY}{file.name}",
                Callback=log_progress,
            )

    def handle(self, *, directory: pathlib.Path, wet_run, **options):
        client = pilotage_s3_client()
        response = client.list_objects_v2(
            Bucket=settings.PILOTAGE_DATASTORE_S3_BUCKET_NAME,
            Prefix=self.DATASTORE_DIRECTORY,
        )
        datastore_files = set()
        if response["KeyCount"]:
            datastore_files.update(
                metadata["Key"].replace(self.DATASTORE_DIRECTORY, "") for metadata in response["Contents"]
            )
        self.stdout.write(f"Files in datastore's {self.DATASTORE_DIRECTORY!r}: {sorted(datastore_files)}")

        local_files = set(file.name for file in directory.glob(f"{self.FILENAME_PREFIX}*.tar.gz"))
        self.stdout.write(f"Files in local's {directory.name!r}: {sorted(local_files)}")

        files_to_upload = local_files - datastore_files
        self.stdout.write(f"Files to upload: {sorted(files_to_upload)}")

        for filename in files_to_upload:
            self.stdout.write(f"Uploading {filename!r}...")
            self._upload_file(directory / filename, wet_run=wet_run)
