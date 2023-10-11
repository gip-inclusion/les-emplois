import json

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand

from itou.utils.storage.s3 import s3_client


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--auto-expire", action="store_true", dest="autoexpire")

    def handle(self, *args, autoexpire=False, **options):
        is_minio = self.check_minio()
        client = s3_client()
        bucket = settings.AWS_STORAGE_BUCKET_NAME
        try:
            client.create_bucket(Bucket=bucket)
        except client.exceptions.BucketAlreadyOwnedByYou:
            pass

        policy_statements = [
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
        ]
        if is_minio:
            policy_statements = [stmt for stmt in policy_statements if "NotResource" not in stmt]
        client.put_bucket_policy(
            Bucket=bucket,
            Policy=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": policy_statements,
                }
            ),
        )

        protocol = "https" if settings.ITOU_ENVIRONMENT != "DEV" else "http"
        allowed_origins = []
        for origin in settings.ALLOWED_HOSTS:
            if origin.startswith("."):
                origin = f"*{origin}"
            allowed_origins.append(f"{protocol}://{origin}")
        if not is_minio:
            # MinIO does not support setting CORS.
            client.put_bucket_cors(
                Bucket=bucket,
                CORSConfiguration={
                    "CORSRules": [
                        {
                            "AllowedHeaders": ["Cache-Control", "X-Requested-With"],
                            "AllowedMethods": ["GET", "PUT", "POST", "DELETE", "HEAD"],
                            "AllowedOrigins": allowed_origins,
                            "ExposeHeaders": ["ETag", "Location"],
                        }
                    ]
                },
            )

        if autoexpire:
            assert settings.ITOU_ENVIRONMENT == "DEV"
            client.put_bucket_lifecycle_configuration(
                Bucket=bucket,
                LifecycleConfiguration={
                    "Rules": [
                        {
                            "Expiration": {"Days": 7},
                            "Filter": {},
                            "Status": "Enabled",
                        },
                    ],
                },
            )

    def check_minio(self):
        response = httpx.head(settings.AWS_S3_ENDPOINT_URL)
        # Response has a bad request status code, but we don’t care.
        try:
            return response.headers["Server"] == "MinIO"
        except KeyError:
            return False
