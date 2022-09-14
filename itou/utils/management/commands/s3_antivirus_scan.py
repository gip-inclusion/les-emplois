import os
import pathlib
import shutil
import stat
import subprocess
import tempfile
import time

import boto3
from django.core.management.base import BaseCommand, CommandError

from itou.utils.storage.s3 import API_CONNECTION_DICT


class Command(BaseCommand):
    help = "Run ClamAV antivirus scan on files hosted in an S3 like bucket."

    def add_arguments(self, parser):
        parser.add_argument("bucket")

    def handle(self, *args, **options):
        if not os.environ.get("CC_CLAMAV", False):
            raise CommandError("ClamAV does not seem to be deployed in the current environment")

        with tempfile.TemporaryDirectory() as workdir:
            # TODO: Scan in batches for production. Limit the file size?
            self.stderr.write("Downloading files...")
            files = self.download_files(options["bucket"], workdir)

            self.stderr.write("Shuffling permissions")
            shutil.chown(workdir, group="clamav")
            os.chmod(workdir, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP)
            for filepath in files:
                shutil.chown(filepath, group="clamav")
                os.chmod(filepath, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)

            self.stderr.write("Scanning in sequence...")
            total_time = 0
            for filepath in files:
                start = time.perf_counter()
                result = self.scan(filepath)
                total_time += time.perf_counter() - start
                if result:
                    self.stdout.write(f"“{filepath}” is a virus.")
            self.stderr.write(f"Scanned {len(files)} in {total_time}s. {total_time / len(files)}s per file.")

            self.stderr.write("Scanning in parallel...")
            start = time.perf_counter()
            self.scan(workdir)
            elapsed = time.perf_counter() - start
            self.stderr.write(f"Scanned {len(files)} in {elapsed}s. {elapsed / len(files)}s per file.")

    def download_files(self, bucket_name, workdir):
        # TODO: download concurrently with asyncio?
        files = []
        s3 = boto3.resource("s3", **API_CONNECTION_DICT)
        bucket = s3.Bucket(name=bucket_name)
        for i, object_summary in enumerate(bucket.objects.all()):
            key = object_summary.key
            filename = pathlib.Path(key).name
            dest = pathlib.Path(workdir) / filename
            s3.meta.client.download_file(Bucket=bucket_name, Key=key, Filename=str(dest))
            files.append(dest)
            if i >= 10_000:
                break
        return files

    @staticmethod
    def scan(path):
        result = subprocess.run(
            ["clamdscan", "--no-summary", "--infected", str(path)],
            capture_output=True,
            check=False,
        )
        return bool(result.returncode)
