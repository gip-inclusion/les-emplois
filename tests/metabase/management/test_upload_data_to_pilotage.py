import io

import pytest
from django.core.management import call_command
from django.utils import timezone

from itou.utils.storage.s3 import pilotage_s3_client


@pytest.mark.usefixtures("temporary_bucket")
def test_command_call(tmp_path, snapshot, caplog):
    tmp_path.joinpath("fluxIAE_ITOU_.tar.gz").write_bytes(b"Hello World")
    call_command("upload_data_to_pilotage", tmp_path.as_posix(), "--wet-run")
    assert caplog.messages[:-1] == snapshot
    assert caplog.messages[-1].startswith(
        "Management command itou.metabase.management.commands.upload_data_to_pilotage succeeded in"
    )


@pytest.mark.usefixtures("temporary_bucket")
def test_command_idempotence(tmp_path, settings):
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


@pytest.mark.usefixtures("temporary_bucket")
def test_command_check_content_length(caplog, snapshot, tmp_path, settings):
    client = pilotage_s3_client()
    filename = "fluxIAE_ITOU_.tar.gz"
    tmp_path.joinpath(filename).write_bytes(b"Hello World")

    client.upload_fileobj(io.BytesIO(), Bucket=settings.PILOTAGE_DATASTORE_S3_BUCKET_NAME, Key=f"flux-iae/{filename}")
    call_command("upload_data_to_pilotage", tmp_path.as_posix(), "--wet-run")
    assert (
        client.get_object(Bucket=settings.PILOTAGE_DATASTORE_S3_BUCKET_NAME, Key=f"flux-iae/{filename}")["Body"].read()
        == b"Hello World"
    )
    assert caplog.messages[:-1] == snapshot
    assert caplog.messages[-1].startswith(
        "Management command itou.metabase.management.commands.upload_data_to_pilotage succeeded in"
    )


def test_command_retries(caplog, snapshot, tmp_path, settings, mocker):
    filename = "fluxIAE_ITOU_.tar.gz"
    tmp_path.joinpath(filename).touch()
    mocker.patch("itou.metabase.management.commands.upload_data_to_pilotage.Command._upload_file", return_value=None)

    call_command("upload_data_to_pilotage", tmp_path.as_posix(), "--wet-run")
    assert caplog.messages[:-1] == snapshot
    assert caplog.messages[-1].startswith(
        "Management command itou.metabase.management.commands.upload_data_to_pilotage succeeded in"
    )
