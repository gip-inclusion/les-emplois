import datetime
import io
import os
import re
import uuid

import httpx
import pytest
from botocore.config import Config
from django.conf import settings
from django.core.files.storage import default_storage, storages
from django.core.management import call_command
from django.utils import timezone

from itou.antivirus.models import Scan
from itou.approvals.enums import ProlongationReason
from itou.files.models import File
from itou.utils.storage.s3 import TEMPORARY_STORAGE_PREFIX, s3_client
from tests.approvals.factories import ProlongationFactory, ProlongationRequestFactory
from tests.communications.factories import AnnouncementItemFactory
from tests.files.factories import FileFactory
from tests.geiq_assessments.factories import AssessmentFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.siae_evaluations.factories import EvaluatedAdministrativeCriteriaFactory, EvaluatedJobApplicationFactory
from tests.utils.test_s3 import default_storage_ls_files


@pytest.mark.usefixtures("temporary_bucket")
def test_urls():
    file = FileFactory()
    with io.BytesIO() as content:
        default_storage.save("test_file.pdf", content)

    assert file.url() == default_storage.url(file.key)
    assert file.public_url() == storages["public"].url(file.key)


@pytest.mark.usefixtures("temporary_bucket")
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


@pytest.mark.skipif(os.getenv("CI") != "true", reason="Not using to Cellar")
@pytest.mark.xfail
@pytest.mark.usefixtures("temporary_bucket")
def test_cellar_does_not_support_checksum_validation():
    client = s3_client()
    client.config = Config()
    client.put_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Body=b"", Key="file")


@pytest.mark.usefixtures("temporary_bucket")
def test_copy(pdf_file):
    key = "resume/11111111-1111-1111-1111-111111111111.pdf"
    default_storage.save(key, pdf_file)
    existing_file = FileFactory(key=key)

    new_file = existing_file.copy()
    assert re.match(r"resume/[-0-9a-z]*.pdf", new_file.key)

    assert default_storage_ls_files() == sorted([key, new_file.key])
    with default_storage.open(existing_file.key) as old, default_storage.open(new_file.key) as new:
        assert old.read() == new.read()


@pytest.mark.usefixtures("temporary_bucket")
def test_delete_unused_files_from_database(caplog):
    old_orphan = FileFactory()
    job_application = JobApplicationFactory()
    ProlongationRequestFactory(report_file=FileFactory(), reason=ProlongationReason.SENIOR)
    ProlongationFactory(report_file=FileFactory(), reason=ProlongationReason.SENIOR)
    scan = Scan.objects.create(file=FileFactory(), clamav_signature="toto")
    AnnouncementItemFactory(with_image=True)
    AssessmentFactory(with_submission_requirements=True)
    evaluated_job_application = EvaluatedJobApplicationFactory(
        job_application=job_application  # Don't create a new resume
    )
    EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=evaluated_job_application)
    # Make all files at least one day old
    File.objects.all().update(last_modified=timezone.now() - datetime.timedelta(days=1))

    FileFactory()  # Too recent orphan file
    assert File.objects.all().count() == 11

    client = s3_client()
    for key in File.objects.values_list("key", flat=True):
        with io.BytesIO() as content:
            client.upload_fileobj(content, Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key)

    call_command("delete_unused_files")

    assert File.objects.all().count() == 9
    assert not File.objects.filter(pk__in=[old_orphan.pk, scan.file_id]).exists()

    assert caplog.messages[:-1] == [
        "Starting unused file removal",
        "Deleted 2 orphans files from database",
        "Checking existing files: 9 files in database",
        "Completed bucket cleaning: found unknown=2 and temporary=0 files in the bucket, removed=0 files",
    ]
    assert caplog.messages[-1].startswith(
        "Management command itou.files.management.commands.delete_unused_files succeeded in"
    )


def test_delete_unused_files_from_s3(temporary_bucket, caplog, mocker):
    client = s3_client()
    existing_file = FileFactory()
    missing_file = FileFactory()
    # Create job applications so that these files are not orphans
    JobApplicationFactory(resume=existing_file)
    JobApplicationFactory(resume=missing_file)

    # create unknown files in the s3
    keys = [
        f"{TEMPORARY_STORAGE_PREFIX}/test.pdf",  # temporary file (will be ignored)
        existing_file.key,  # exists in db
        # files to clean
        "resume/11111111-1111-1111-1111-111111111111.pdf",
        "evaluations/test.xlsx",
        "prolongation_report/test.xlsx",
    ]
    for key in keys:
        with io.BytesIO() as content:
            client.upload_fileobj(content, Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key)

    # With the default 1 day delay, no file will be removed. It's a security to ensure we don't delete
    # a file that was just uploaded before the File object was commited to the database.
    call_command("delete_unused_files")
    assert File.objects.count() == 2  # No changes in db
    assert caplog.messages[:-1] == [
        "Starting unused file removal",
        "Deleted 0 orphans files from database",
        "Checking existing files: 2 files in database",
        "Completed bucket cleaning: found unknown=3 and temporary=1 files in the bucket, removed=0 files",
        f"1 database files do not exist in the bucket: [{missing_file.key!r}]",
    ]
    assert caplog.messages[-1].startswith(
        "Management command itou.files.management.commands.delete_unused_files succeeded in"
    )
    assert sorted(
        obj["Key"] for obj in client.list_objects_v2(Bucket=settings.AWS_STORAGE_BUCKET_NAME)["Contents"]
    ) == sorted(keys)

    # Without delay
    mocker.patch("itou.files.management.commands.delete_unused_files.CLEANING_DELAY", datetime.timedelta())
    caplog.clear()

    call_command("delete_unused_files")
    assert File.objects.count() == 2  # No changes in db
    assert caplog.messages[:-1] == [
        "Starting unused file removal",
        "Deleted 0 orphans files from database",
        "Checking existing files: 2 files in database",
        "Completed bucket cleaning: found unknown=3 and temporary=1 files in the bucket, removed=3 files",
        f"1 database files do not exist in the bucket: [{missing_file.key!r}]",
    ]
    assert caplog.messages[-1].startswith(
        "Management command itou.files.management.commands.delete_unused_files succeeded in"
    )
    assert sorted(
        obj["Key"] for obj in client.list_objects_v2(Bucket=settings.AWS_STORAGE_BUCKET_NAME)["Contents"]
    ) == sorted(keys[:2])
