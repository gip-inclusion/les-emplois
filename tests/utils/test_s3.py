import uuid

import pytest
from django.core.files.storage import default_storage

from itou.utils.enums import ItouEnvironment
from itou.utils.storage.s3 import NoObjectsInBucket, delete_all_objects_versions, s3_client


def default_storage_ls_files(directory=""):
    # List all files in default_storage in a recusrive way
    # Always call without subdirectory
    result = []
    subdirectories, files = default_storage.listdir(directory)
    result += files
    for subdirectory in subdirectories:
        result += [f"{subdirectory}/{file}" for file in default_storage_ls_files(subdirectory)]
    return sorted(result)


@pytest.mark.empty_temporary_bucket_expected
def test_delete_all_objects_versions(temporary_bucket, pdf_file):
    client = s3_client()

    with pytest.raises(NoObjectsInBucket):
        delete_all_objects_versions(client, bucket=temporary_bucket)

    # Upload a file...
    client.upload_fileobj(
        Fileobj=pdf_file,
        Bucket=temporary_bucket,
        Key=str(uuid.uuid4()),
    )

    # ... then delete it
    delete_all_objects_versions(client, bucket=temporary_bucket)

    # No objects should be left
    with pytest.raises(NoObjectsInBucket):
        delete_all_objects_versions(client, bucket=temporary_bucket)


def test_delete_all_objects_versions_is_forbidden_in_production(settings):
    settings.ITOU_ENVIRONMENT = ItouEnvironment.PROD

    with pytest.raises(RuntimeError, match="Not going to delete all objects versions in production, sorry mate."):
        delete_all_objects_versions(None, bucket=None)
