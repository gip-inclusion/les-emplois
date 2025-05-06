import io
import os
import re
import uuid

import httpx
import pytest
from botocore.config import Config
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management import call_command
from pytest_django.asserts import assertQuerySetEqual

from itou.files.models import File
from itou.utils.storage.s3 import s3_client
from tests.files.factories import FileFactory


def test_sync_files_ignores_temporary_storage(temporary_bucket, caplog):
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
    assert caplog.messages[:-1] == ["Completed bucket sync: found permanent=3 and temporary=1 files in the bucket"]
    assert caplog.messages[-1].startswith(
        "Management command itou.files.management.commands.sync_s3_files succeeded in"
    )


def test_bucket_policy_for_anonymous_user():
    base_url = f"{settings.AWS_S3_ENDPOINT_URL}{settings.AWS_STORAGE_BUCKET_NAME}/{default_storage.location}"
    response = httpx.head(f"{base_url}/test_file.pdf")
    assert response.status_code == 403

    with io.BytesIO() as content:
        default_storage.save("test_file.pdf", content)
    response = httpx.head(f"{base_url}/test_file.pdf")
    assert response.status_code == 403

    # Anything under the resume prefix is public.
    filename = f"{uuid.uuid4()}.pdf"
    root_url = f"{settings.AWS_S3_ENDPOINT_URL}{settings.AWS_STORAGE_BUCKET_NAME}"
    s3_client().put_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Body=b"", Key=f"resume/{filename}")
    response = httpx.head(f"{root_url}/resume/{filename}")
    assert response.status_code == 200

    s3_client().put_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Body=b"", Key=f"news-images/{filename}")
    response = httpx.head(f"{root_url}/news-images/{filename}")
    assert response.status_code == 200

    with io.BytesIO() as content:
        response = httpx.put(base_url, content=content)
    assert response.status_code == 403


def test_deletion(temporary_bucket):
    client = s3_client()
    key = "evaluations/test.xlsx"
    with io.BytesIO() as content:
        client.upload_fileobj(content, Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key)
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.AWS_STORAGE_BUCKET_NAME):
        client.delete_objects(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Delete={"Objects": [{"Key": obj["Key"]} for obj in page["Contents"]]},
        )
    [page_after_deletion] = paginator.paginate(Bucket=settings.AWS_STORAGE_BUCKET_NAME)
    assert page_after_deletion["KeyCount"] == 0


def test_sync_files_check_existing(temporary_bucket, caplog):
    client = s3_client()
    for key in [
        "resume/11111111-1111-1111-1111-111111111111.pdf",
        "evaluations/test.xlsx",
        "prolongation_report/test.xlsx",
    ]:
        with io.BytesIO() as content:
            client.upload_fileobj(content, Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key)
    existing_file = FileFactory()
    call_command("sync_s3_files", check_existing=True)
    assertQuerySetEqual(
        File.objects.values_list("key", flat=True),
        [
            "resume/11111111-1111-1111-1111-111111111111.pdf",
            "evaluations/test.xlsx",
            "prolongation_report/test.xlsx",
            existing_file.key,
        ],
        ordered=False,
    )
    assert caplog.messages[:-1] == [
        "Checking existing files: 1 files in database before sync",
        "Completed bucket sync: found permanent=3 and temporary=0 files in the bucket",
        "permanent=0 files already in database before sync",
        f"1 database files do not exist in the bucket: [{existing_file.key!r}]",
    ]
    assert caplog.messages[-1].startswith(
        "Management command itou.files.management.commands.sync_s3_files succeeded in"
    )


@pytest.mark.skipif(os.getenv("CI") != "true", reason="Not using to Cellar")
@pytest.mark.xfail
def test_cellar_does_not_support_checksum_validation():
    client = s3_client()
    client.config = Config()
    client.put_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Body=b"", Key="file")


def test_copy(pdf_file):
    key = "resume/11111111-1111-1111-1111-111111111111.pdf"
    default_storage.save(key, pdf_file)
    existing_file = FileFactory(key=key)

    new_file = existing_file.copy()
    assert re.match(r"resume/[-0-9a-z]*.pdf", new_file.key)

    with default_storage.open(key) as old, default_storage.open(new_file.key) as new:
        assert old.read() == new.read()
