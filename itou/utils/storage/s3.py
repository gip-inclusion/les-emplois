import boto3
from django.conf import settings
from storages.backends.s3 import S3Storage


TEMPORARY_STORAGE_PREFIX = "temporary_storage"


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        aws_access_key_id=settings.AWS_S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_S3_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
        config=settings.AWS_S3_CLIENT_CONFIG,
    )


def pilotage_s3_client():
    """There is an S3 bucket dedicated to sharing files with Pilotage"""
    return boto3.client(
        "s3",
        endpoint_url=settings.PILOTAGE_DATASTORE_S3_ENDPOINT_URL,
        aws_access_key_id=settings.PILOTAGE_DATASTORE_S3_ACCESS_KEY,
        aws_secret_access_key=settings.PILOTAGE_DATASTORE_S3_SECRET_KEY,
        config=settings.AWS_S3_CLIENT_CONFIG,
    )


class PublicStorage(S3Storage):
    # Not using the S3StaticStorage backend to ensure the listdir() operation remains forbidden.
    # Don’t sign URLs, objects are public.
    querystring_auth = False
