import concurrent.futures
import datetime
import os
import shutil
import stat
import subprocess
import tempfile

import boto3
from botocore.client import Config
from botocore.exceptions import ConnectionError as BotoConnectionError, HTTPClientError
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ...models import FileScanReport


class Command(BaseCommand):
    help = "Run ClamAV antivirus scan on files hosted in an S3 like bucket."
    BATCH_SIZE = 10_000

    def add_arguments(self, parser):
        parser.add_argument("bucket")
        parser.add_argument("--daily", action="store_true", default=False)

    def handle(self, *args, **options):
        if options["daily"]:
            cutoff = datetime.datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            start = cutoff - datetime.timedelta(days=1)

            def s3_obj_filter_func(obj_summary):
                return start <= obj_summary["LastModified"] < cutoff

        else:

            def s3_obj_filter_func(obj_summary):
                return True

        self.client = boto3.client(
            "s3",
            endpoint_url=f"https://{settings.S3_STORAGE_ENDPOINT_DOMAIN}",
            aws_access_key_id=settings.S3_STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_STORAGE_SECRET_ACCESS_KEY,
            region_name=settings.S3_STORAGE_BUCKET_REGION,
            config=Config(signature_version="s3v4"),
        )
        paginator = self.client.get_paginator("list_objects_v2")
        page_iterator = paginator.paginate(Bucket=options["bucket"])
        scanned = 0
        while True:
            with tempfile.TemporaryDirectory() as workdir:
                filepath_s3key, has_next = self.download_files(page_iterator, s3_obj_filter_func, workdir)

                shutil.chown(workdir, group="clamav")
                os.chmod(workdir, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP)
                for filepath in filepath_s3key:
                    shutil.chown(filepath, group="clamav")
                    os.chmod(filepath, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)

                result = self.scan(workdir)
                if result is not None:
                    self.process_report(result, filepath_s3key)
                scanned += len(filepath_s3key)

                if not has_next:
                    break

    def download_files(self, page_iterator, filter_func, workdir):
        obj_summaries_to_download = []
        for page in page_iterator:
            bucket_name = page["Name"]
            obj_summary = page["Contents"]
            obj_summaries_to_download.extend(s for s in obj_summary if filter_func(s))
            if len(obj_summaries_to_download) >= self.BATCH_SIZE:
                has_next = page["IsTruncated"]
                break
        else:
            has_next = False
        if not obj_summaries_to_download:
            return [], False

        def download_file_descriptor_with_retry(bucket_name, key, fd):
            with os.fdopen(fd, "wb") as fileobj:
                for _ in range(5):
                    try:
                        self.client.download_fileobj(bucket_name, key, fileobj)
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
            for obj_summary in obj_summaries_to_download:
                key = obj_summary["Key"]
                fd, path = tempfile.mkstemp(dir=workdir)
                batch_futures.append(
                    executor.submit(
                        download_file_descriptor_with_retry,
                        bucket_name,
                        key,
                        fd,
                    )
                )
                filepath_s3key[path] = key
            _done, not_done = concurrent.futures.wait(batch_futures, timeout=3600)
        if not_done:
            raise CommandError("Could not download files to scan.")
        return filepath_s3key, has_next

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
        file_reports = []
        for line in report.splitlines():
            local_path, details = line.split(":", maxsplit=1)
            signature, _found = details.strip().split(" ", maxsplit=1)
            s3key = filepath_s3key[local_path]
            file_reports.append(FileScanReport(key=s3key, signature=signature))
        FileScanReport.objects.bulk_create(file_reports, ignore_conflicts=True)
