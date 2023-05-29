"""
Useful functions to interact with an S3 bucket.
"""

import boto3
from botocore.client import Config
from django.conf import settings


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.S3_STORAGE_ENDPOINT_DOMAIN}",
        aws_access_key_id=settings.S3_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.S3_STORAGE_SECRET_ACCESS_KEY,
        region_name=settings.S3_STORAGE_BUCKET_REGION,
        config=Config(signature_version="s3v4"),
    )


class S3Upload:
    def __init__(self, kind="default"):
        self.config = self.get_config(kind)

    @property
    def form_values(self):
        """
        Returns a dict like this:
        {
            "url": "https://cellar-c2.services.clever-cloud.com/bucket_name",
            "fields": {
                'key': 'key_path',
                'x-amz-algorithm': 'AWS4-HMAC-SHA256',
                'x-amz-credential': '',
                'x-amz-date': '',
                'policy': '',
                'x-amz-signature': '',
            }
        }
        """

        client = s3_client()
        key_path = self.config["key_path"] + "/${filename}"
        expiration = self.config["upload_expiration"]
        values_dict = client.generate_presigned_post(settings.S3_STORAGE_BUCKET_NAME, key_path, ExpiresIn=expiration)
        values_dict["fields"].pop("key")
        return values_dict

    @staticmethod
    def get_config(kind):
        config = settings.STORAGE_UPLOAD_KINDS[kind]
        default_options = settings.STORAGE_UPLOAD_KINDS["default"]
        config = default_options | config

        key_path = config["key_path"]
        if key_path.startswith("/") or key_path.endswith("/"):
            raise ValueError("key_path should not begin or end with a slash")

        config["allowed_mime_types"] = ",".join(config["allowed_mime_types"])

        return config
