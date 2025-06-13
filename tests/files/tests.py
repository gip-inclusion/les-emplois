import datetime
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
from django.utils import timezone
from pytest_django.asserts import assertQuerySetEqual

from itou.antivirus.models import Scan
from itou.approvals.enums import ProlongationReason
from itou.files.models import File
from itou.utils.storage.s3 import s3_client
from tests.approvals.factories import ProlongationFactory, ProlongationRequestFactory
from tests.communications.factories import AnnouncementItemFactory
from tests.files.factories import FileFactory
from tests.geiq_assessments.factories import AssessmentFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.siae_evaluations.factories import EvaluatedAdministrativeCriteriaFactory, EvaluatedJobApplicationFactory


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


def test_sync_files_ignores_temporary_storage(temporary_bucket, caplog):
    client = s3_client()
    for key in [
        "resume/11111111-1111-1111-1111-111111111111.pdf",
        "evaluations/test.xlsx",
        "prolongation_report/test.xlsx",
    ]:
        with io.BytesIO() as content:
            client.upload_fileobj(content, Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key)
    existing_file = FileFactory()
    call_command("sync_s3_files")
    assertQuerySetEqual(
        File.objects.values_list("id", flat=True),
        [
            "resume/11111111-1111-1111-1111-111111111111.pdf",
            "evaluations/test.xlsx",
            "prolongation_report/test.xlsx",
            existing_file.key,
        ],
        ordered=False,
    )
    assertQuerySetEqual(
        File.objects.filter(deleted_at__isnull=False).values_list("key", flat=True),
        [
            "resume/11111111-1111-1111-1111-111111111111.pdf",
            "evaluations/test.xlsx",
            "prolongation_report/test.xlsx",
        ],
        ordered=False,
    )
    assert caplog.messages[:-1] == [
        "Checking existing files: 1 files in database before sync",
        "Completed bucket sync: found permanent=3 and temporary=0 files in the bucket",
        "permanent=0 files already in database before sync",
        f"1 database files do not exist in the bucket: [{existing_file.id!r}]",
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
    existing_file = FileFactory(id=key)

    new_file = existing_file.copy()
    assert re.match(r"resume/[-0-9a-z]*.pdf", new_file.key)

    with default_storage.open(key) as old, default_storage.open(new_file.key) as new:
        assert old.read() == new.read()


def test_find_orphans(caplog):
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

    call_command("find_orphan_files")

    orphan_pks = set(File.objects.filter(deleted_at__isnull=False).values_list("pk", flat=True))
    assert orphan_pks == {old_orphan.pk, scan.file_id}

    assert caplog.messages[:-1] == ["Marked 2 orphans files for deletion"]
    assert caplog.messages[-1].startswith(
        "Management command itou.files.management.commands.find_orphan_files succeeded in"
    )


def test_purge_files(caplog):
    in_the_past = timezone.now() - datetime.timedelta(days=1)
    to_purge = FileFactory(deleted_at=in_the_past)
    not_an_orphan = JobApplicationFactory(resume__deleted_at=in_the_past).resume
    FileFactory(deleted_at=in_the_past)  # File without S3 object (remove anyway)
    too_recently_marked = FileFactory(deleted_at=timezone.now())

    for file in [to_purge, not_an_orphan]:
        with io.BytesIO() as content:
            default_storage.save(file.key, content)

    call_command("purge_files")

    assert set(File.objects.values_list("pk", flat=True)) == {not_an_orphan.pk, too_recently_marked.pk}

    assert caplog.messages[:-1] == [
        f"Could not delete protected file {not_an_orphan.key}",
        "Purged 2 files",
    ]
    assert caplog.messages[-1].startswith("Management command itou.files.management.commands.purge_files succeeded in")


def test_update_ids():
    file = FileFactory()
    job_application = JobApplicationFactory(resume=file)
    prolongation_request = ProlongationRequestFactory(report_file=file, reason=ProlongationReason.SENIOR)
    prolongation = ProlongationFactory(report_file=file, reason=ProlongationReason.SENIOR)
    scan = Scan.objects.create(file=file, clamav_signature="toto")
    announcement_item = AnnouncementItemFactory()
    announcement_item.image_storage = file
    announcement_item.save()
    assessment = AssessmentFactory(
        summary_document_file=file, structure_financial_assessment_file=file, action_financial_assessment_file=file
    )
    # Not a OneToOneField
    evaluated_job_application = EvaluatedJobApplicationFactory(
        job_application=job_application  # Don't create a new resume
    )
    evaluated_administrative_criteria_1 = EvaluatedAdministrativeCriteriaFactory(
        proof=file, evaluated_job_application=evaluated_job_application
    )
    evaluated_administrative_criteria_2 = EvaluatedAdministrativeCriteriaFactory(
        proof=file, evaluated_job_application=evaluated_job_application
    )

    call_command("update_ids")

    new_file = File.objects.get()
    assert new_file.key == file.key
    assert new_file.id != file.id

    job_application.refresh_from_db()
    assert job_application.resume_id == new_file.id
    prolongation_request.refresh_from_db()
    assert prolongation_request.report_file_id == new_file.id
    prolongation.refresh_from_db()
    assert prolongation.report_file_id == new_file.id
    scan.refresh_from_db()
    assert scan.file_id == new_file.id
    announcement_item.refresh_from_db()
    assert announcement_item.image_storage_id == new_file.id
    assessment.refresh_from_db()
    assert assessment.summary_document_file_id == new_file.id
    assert assessment.structure_financial_assessment_file_id == new_file.id
    assert assessment.action_financial_assessment_file_id == new_file.id
    evaluated_administrative_criteria_1.refresh_from_db()
    assert evaluated_administrative_criteria_1.proof_id == new_file.id
    evaluated_administrative_criteria_2.refresh_from_db()
    assert evaluated_administrative_criteria_2.proof_id == new_file.id
