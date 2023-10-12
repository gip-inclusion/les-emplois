import boto3
from botocore.client import Config
from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage


TEMPORARY_STORAGE_PREFIX = "temporary_storage"


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        aws_access_key_id=settings.AWS_S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_S3_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
        config=Config(signature_version="s3v4"),
    )


class PublicStorage(S3Boto3Storage):
    # Not using the S3StaticStorage backend to ensure the listdir() operation remains forbidden.
    # Don’t sign URLs, objects are public.
    querystring_auth = False
