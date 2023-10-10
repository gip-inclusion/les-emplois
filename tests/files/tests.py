import io

import httpx
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.utils import timezone
from pytest_django.asserts import assertQuerySetEqual

from itou.approvals.enums import ProlongationReason
from itou.files.models import File
from itou.utils.storage.s3 import s3_client
from tests.approvals.factories import ProlongationFactory


def test_report_file_link():
    prolongation = ProlongationFactory(reason=ProlongationReason.RQTH)

    assert prolongation.report_file is None

    file_path = "prolongation_report/test.xslx"
    report_file = File(file_path, timezone.now())
    report_file.save()

    prolongation.report_file = report_file
    prolongation.save()

    assert (
        prolongation.report_file.link
        == f"{settings.AWS_S3_ENDPOINT_URL}{settings.AWS_STORAGE_BUCKET_NAME}/{default_storage.location}/{file_path}"
    )


def test_sync_files_ignores_temporary_storage(temporary_bucket):
    client = s3_client()
    for key in [
        "resume/11111111-1111-1111-1111-111111111111.pdf",
        "evaluations/test.xlsx",
        "prolongation_report/test.xlsx",
        "temporary_storage/test.xlsx",
    ]:
        with io.BytesIO() as content:
            client.upload_fileobj(content, Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key)
    call_command("sync_s3_files")
    assertQuerySetEqual(
        File.objects.values_list("key", flat=True),
        [
            "resume/11111111-1111-1111-1111-111111111111.pdf",
            "evaluations/test.xlsx",
            "prolongation_report/test.xlsx",
        ],
        ordered=False,
    )


def test_bucket_policy_for_anonymous_user():
    base_url = f"{settings.AWS_S3_ENDPOINT_URL}{settings.AWS_STORAGE_BUCKET_NAME}/{default_storage.location}"
    response = httpx.head(f"{base_url}/test_file.pdf")
    assert response.status_code == 404
    with io.BytesIO() as content:
        default_storage.save("test_file.pdf", content)
    response = httpx.head(f"{base_url}/test_file.pdf")
    assert response.status_code == 200
    with io.BytesIO() as content:
        response = httpx.put(base_url, content=content)
    assert response.status_code == 403
