"""
The FluxIAE file contains data used by les emplois and is uploaded to us directly by a supporting organization.
The same file is also parsed by the Pilotage, shared via an S3 bucket.

This command uploads the file from where it has been stored to the S3 bucket for sharing.
"""

import pathlib
import threading
from pathlib import Path

from botocore.exceptions import ClientError
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

    def _get_key_content_length(self, client, key) -> int | None:
        try:
            response = client.head_object(Bucket=settings.PILOTAGE_DATASTORE_S3_BUCKET_NAME, Key=key)
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return None
            raise e
        else:
            return int(response["ContentLength"])

    def _upload_file(self, client, file: pathlib.Path, key):
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
                    self.logger.info(
                        f"> {file.name}: {filesizeformat(bytes_transferred)}/{filesizeformat(file_size)} transferred ({progress}%)."  # noqa: E501
                    )
                    previous_progress = progress

        client.upload_file(
            Filename=file.absolute(),
            Bucket=settings.PILOTAGE_DATASTORE_S3_BUCKET_NAME,
            Key=key,
            Callback=log_progress,
        )

    def handle(self, *, directory: pathlib.Path, wet_run, **options):
        local_files = set(file.name for file in directory.glob(f"{self.FILENAME_PREFIX}*.tar.gz"))
        self.logger.info(f"Files in local's {directory.name!r}: {sorted(local_files)}")

        client = pilotage_s3_client()
        for filename in local_files:
            local_file = directory / filename
            datastore_key = f"{self.DATASTORE_DIRECTORY}{filename}"
            self.logger.info(f"Checking that {filename!r} match with {datastore_key!r}...")

            local_content_length = local_file.stat().st_size
            datastore_content_length = self._get_key_content_length(client, datastore_key)
            tries = 0
            while datastore_content_length is None or datastore_content_length != local_file.stat().st_size:
                self.logger.info(
                    f"{filename!r} doesn't match with {datastore_key!r}: "
                    f"{datastore_content_length=} {local_content_length=}"
                )
                if wet_run:
                    self.logger.info(f"Uploading {filename!r} to {datastore_key!r}...")
                    self._upload_file(client, local_file, key=datastore_key)
                    # Sometime and for some unknown reason the upload doesn't fully complete,
                    # but it never happens when the command is launched manually :(.
                    datastore_content_length = self._get_key_content_length(client, datastore_key)
                    tries += 1
                    if tries >= 3:
                        self.logger.warning(
                            f"{filename!r} still doesn't match with {datastore_key!r} after {tries} tries."
                        )
                        break
                else:
                    break
            else:
                self.logger.info(f"{filename!r} match with {datastore_key!r}!")
