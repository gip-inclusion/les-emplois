import json

from django.conf import settings
from django.core.management.base import BaseCommand

from itou.utils.storage.s3 import s3_client


class Command(BaseCommand):
    def handle(self, *args, **options):
        client = s3_client()
        bucket = settings.S3_STORAGE_BUCKET_NAME
        try:
            client.create_bucket(Bucket=bucket)
        except s3_client.exceptions.BucketAlreadyOwnedByYou:
            pass

        client.put_bucket_policy(
            Bucket=bucket,
            Policy=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Sid": "AllowPublicRead",
                            "Effect": "Allow",
                            "Principal": {"AWS": "*"},
                            "Action": "s3:GetObject",
                            "Resource": f"arn:aws:s3:::{bucket}/*",
                        },
                        {
                            "Sid": "AllowPublish",
                            "Effect": "Allow",
                            "Principal": {"AWS": "*"},
                            "Action": "s3:PutObject",
                            "Resource": [
                                f"arn:aws:s3:::{bucket}/*.pdf",
                                f"arn:aws:s3:::{bucket}/*.PDF",
                                f"arn:aws:s3:::{bucket}/*.xlsx",
                                f"arn:aws:s3:::{bucket}/*.XLSX",
                            ],
                        },
                        {
                            "Sid": "DenyPublish",
                            "Effect": "Deny",
                            "Principal": {"AWS": "*"},
                            "Action": "s3:PutObject",
                            "NotResource": [
                                f"arn:aws:s3:::{bucket}/*.pdf",
                                f"arn:aws:s3:::{bucket}/*.PDF",
                                f"arn:aws:s3:::{bucket}/*.xlsx",
                                f"arn:aws:s3:::{bucket}/*.XLSX",
                            ],
                        },
                    ],
                }
            ),
        )

        allowed_headers = ["Cache-Control", "X-Requested-With"]
        protocol = "https" if settings.ITOU_ENVIRONMENT != "DEV" else "http"
        allowed_origins = []
        for origin in settings.ALLOWED_HOSTS:
            if origin.startswith("."):
                origin = f"*{origin}"
            allowed_origins.append(f"{protocol}://{origin}")
        client.put_bucket_cors(
            Bucket=bucket,
            CORSConfiguration={
                "CORSRules": [
                    {
                        "AllowedHeaders": allowed_headers,
                        "AllowedMethods": ["GET", "PUT", "POST", "DELETE", "HEAD"],
                        "AllowedOrigins": allowed_origins,
                        "ExposeHeaders": ["ETag", "Location"],
                    }
                ]
            },
        )
