import concurrent.futures
import os
import shutil
import stat
import subprocess
import tempfile
import time

from botocore.exceptions import ConnectionError as BotoConnectionError, HTTPClientError
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.management.base import CommandError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from itou.antivirus.models import Scan
from itou.files.models import File
from itou.utils.command import BaseCommand
from itou.utils.storage.s3 import s3_client


class Command(BaseCommand):
    help = "Run ClamAV antivirus scan on files hosted in an S3 like bucket."
    # Takes less than 10 seconds to run on a recent machine. Since crons can be
    # interrupted, prefer frequent and quick iterations.
    BATCH_SIZE = 200

    def handle(self, *args, **options):
        start = time.perf_counter()
        now = timezone.now()
        files = File.objects.exclude(scan__clamav_completed_at__gt=now - relativedelta(months=1)).order_by(
            F("scan__clamav_completed_at").asc(nulls_first=True)
        )[: self.BATCH_SIZE]
        # Indicate these files are being processed to concurrent scans.
        files = files.select_for_update(of=["self"], skip_locked=True, no_key=True)
        with tempfile.TemporaryDirectory() as workdir:
            with transaction.atomic():
                filepath_s3key = self.download_files(files, workdir)

                shutil.chown(workdir, group="clamav")
                os.chmod(workdir, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP)
                for filepath in filepath_s3key:
                    shutil.chown(filepath, group="clamav")
                    os.chmod(filepath, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)

                result = self.scan(workdir)
                viruses_keys = self.process_report(result, filepath_s3key) if result is not None else set()

                Scan.objects.bulk_create(
                    [
                        Scan(
                            file=file,
                            clamav_completed_at=now,
                            # On conflict, the virus field is not updated. Assume legitimate files.
                            infected=file.key in viruses_keys,
                        )
                        for file in files
                    ],
                    update_conflicts=True,
                    update_fields=["clamav_completed_at"],
                    unique_fields=["file_id"],
                )
        elapsed = time.perf_counter() - start
        self.stderr.write(f"Scanned {len(files)} files in {elapsed:.2f}s.")

    def download_files(self, files, workdir):
        client = s3_client()

        def download_file_descriptor_with_retry(key, fd):
            with os.fdopen(fd, "wb") as fileobj:
                for _ in range(5):
                    try:
                        client.download_fileobj(settings.AWS_STORAGE_BUCKET_NAME, key, fileobj)
                    except (BotoConnectionError, HTTPClientError):
                        pass
                    else:
                        break

        filepath_s3key = {}
        # More workers result in warnings:
        #
        # Connection pool is full, discarding connection:
        # cellar-c2.services.clever-cloud.com. Connection pool size: 10
        #
        # https://urllib3.readthedocs.io/en/latest/advanced-usage.html#customizing-pool-behavior
        # indicates the default pool size is indeed 10.
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            batch_futures = []
            for file in files:
                fd, path = tempfile.mkstemp(dir=workdir)
                batch_futures.append(executor.submit(download_file_descriptor_with_retry, file.key, fd))
                filepath_s3key[path] = file.key
            _done, not_done = concurrent.futures.wait(batch_futures, timeout=3600)
        if not_done:
            raise CommandError("Could not download files to scan.")
        return filepath_s3key

    @staticmethod
    def scan(path):
        result = subprocess.run(
            ["clamdscan", "--no-summary", "--infected", path],
            capture_output=True,
            text=True,
        )
        match result.returncode:
            case 0:
                return None
            case 1:
                return result.stdout
            case _:
                raise CommandError(result.stderr)

    @staticmethod
    def process_report(report, filepath_s3key):
        viruses = {}
        for line in report.splitlines():
            local_path, details = line.split(":", maxsplit=1)
            signature, _found = details.strip().split(" ", maxsplit=1)
            s3key = filepath_s3key[local_path]
            viruses[s3key] = signature

        viruses_keys = set(viruses)
        scans = []
        for scan in Scan.objects.filter(file_id__in=viruses):
            scan.clamav_signature = viruses.pop(scan.file_id)
            scans.append(scan)
        Scan.objects.bulk_update(scans, fields=["clamav_signature"])
        Scan.objects.bulk_create(Scan(file_id=key, clamav_signature=signature) for key, signature in viruses.items())
        return viruses_keys
