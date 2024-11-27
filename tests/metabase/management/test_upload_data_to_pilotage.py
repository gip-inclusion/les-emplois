import io

import pytest
from django.core.management import call_command
from django.utils import timezone

from itou.utils.storage.s3 import pilotage_s3_client


@pytest.mark.usefixtures("temporary_bucket")
def test_command_call(tmp_path, snapshot):
    tmp_path.joinpath("fluxIAE_ITOU_.tar.gz").write_bytes(b"Hello World")
    stdout = io.StringIO()

    call_command("upload_data_to_pilotage", tmp_path.as_posix(), "--wet-run", stdout=stdout)
    assert stdout.getvalue() == snapshot


@pytest.mark.usefixtures("temporary_bucket")
def test_command_idempotence(tmp_path, settings):
    print("BUCKET", settings.PILOTAGE_DATASTORE_S3_BUCKET_NAME)
    filename = f"fluxIAE_ITOU_{timezone.now():%Y%m%d_%H%M%S}.tar.gz"
    tmp_path.joinpath(filename).touch()

    call_command("upload_data_to_pilotage", tmp_path.as_posix(), "--wet-run")
    response = pilotage_s3_client().list_objects_v2(
        Bucket=settings.PILOTAGE_DATASTORE_S3_BUCKET_NAME,
    )
    assert response["KeyCount"] == 1
    assert response["Contents"][0]["Key"] == f"flux-iae/{filename}"
    modified_at = response["Contents"][0]["LastModified"]

    call_command("upload_data_to_pilotage", tmp_path.as_posix(), "--wet-run")
    response = pilotage_s3_client().list_objects_v2(
        Bucket=settings.PILOTAGE_DATASTORE_S3_BUCKET_NAME,
    )
    assert response["KeyCount"] == 1
    assert response["Contents"][0]["Key"] == f"flux-iae/{filename}"
    assert response["Contents"][0]["LastModified"] == modified_at
