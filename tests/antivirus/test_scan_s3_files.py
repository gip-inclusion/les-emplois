import io

import pytest
from dateutil.relativedelta import relativedelta
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.utils import timezone
from pytest_django.asserts import assertQuerySetEqual

from itou.antivirus.models import Scan
from itou.files.models import File
from tests.antivirus.factories import ScanFactory
from tests.files.factories import FileFactory


@pytest.mark.usefixtures("temporary_bucket")
def test_scan_s3_files(mocker):
    VIRUS = "GLaDOS-Signature"
    now = timezone.now()
    one_week_ago = now - relativedelta(days=7)
    one_month_ago = now - relativedelta(months=1)

    # clean file
    file1 = FileFactory()
    # infected file
    file2 = FileFactory()
    # clean file that was checked > 1 month ago
    file3 = ScanFactory(clamav_completed_at=one_month_ago, infected=False).file
    # clean file that was checked > 1 month ago and is now infected
    file4 = ScanFactory(clamav_completed_at=one_month_ago, infected=False).file
    # infected file that was checked > 1 month ago and is now clean
    file5 = ScanFactory(clamav_completed_at=one_month_ago, clamav_signature=VIRUS, infected=True).file
    # file that was checked in the last month
    file6 = ScanFactory(clamav_completed_at=one_week_ago, infected=False).file

    # save those files in s3 bucket with dummy content
    for key in File.objects.values_list("key", flat=True):
        with io.BytesIO() as content:
            default_storage.save(key, content)

    mocker.patch("itou.antivirus.management.commands.scan_s3_files.timezone.now").return_value = now

    # we mock this function to avoid failures related to missing groups or permission errors
    mocker.patch("itou.antivirus.management.commands.scan_s3_files.shutil.chown")

    # we don't need to manipulate real files
    mocker.patch("itou.antivirus.management.commands.scan_s3_files.os.chmod")

    # files are retrieved from S3 and saved as temporary files
    filepath_s3key = {
        "/tmp/tmp_file1": file1.key,
        "/tmp/tmp_file2": file2.key,
        "/tmp/tmp_file3": file3.key,
        "/tmp/tmp_file4": file4.key,
        "/tmp/tmp_file5": file5.key,
        "/tmp/tmp_file6": file6.key,
    }
    mocker.patch(
        "itou.antivirus.management.commands.scan_s3_files.Command.download_files"
    ).return_value = filepath_s3key

    subprocess_mock = mocker.patch("itou.antivirus.management.commands.scan_s3_files.subprocess.run")
    subprocess_mock.return_value.returncode = 1  # 1 means some files are infected
    subprocess_mock.return_value.stdout = "\n".join(
        [
            f"/tmp/tmp_file2: {VIRUS} FOUND",
            f"/tmp/tmp_file4: {VIRUS} FOUND",
        ]
    )

    call_command("scan_s3_files")

    assertQuerySetEqual(
        Scan.objects.all(),
        [
            (file1.pk, now, "", False),
            (file2.pk, now, VIRUS, True),
            (file3.pk, now, "", False),
            (file4.pk, now, VIRUS, False),
            (file5.pk, now, VIRUS, True),
            (file6.pk, one_week_ago, "", False),
        ],
        transform=lambda s: (s.file_id, s.clamav_completed_at, s.clamav_signature, s.infected),
        ordered=False,
    )
