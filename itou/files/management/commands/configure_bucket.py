import json
from urllib.parse import urljoin

import httpx
from django.conf import settings

from itou.utils.command import BaseCommand
from itou.utils.enums import ItouEnvironment
from itou.utils.storage.s3 import TEMPORARY_STORAGE_PREFIX, s3_client


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
                "Resource": f"arn:aws:s3:::{bucket}/resume/*",
            },
        ]
        client.put_bucket_policy(
            Bucket=bucket,
            Policy=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": policy_statements,
                }
            ),
        )

        # MinIO does not support setting CORS.
        if not is_minio:
            protocol = "https" if settings.ITOU_ENVIRONMENT != ItouEnvironment.DEV else "http"
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
                            "AllowedHeaders": ["Cache-Control", "X-Requested-With"],
                            "AllowedMethods": ["GET", "PUT", "POST", "DELETE", "HEAD"],
                            "AllowedOrigins": allowed_origins,
                            "ExposeHeaders": ["ETag", "Location"],
                        }
                    ]
                },
            )

        auto_expire_rule_filter = {"Prefix": TEMPORARY_STORAGE_PREFIX}
        if autoexpire:
            assert settings.ITOU_ENVIRONMENT == ItouEnvironment.DEV
            auto_expire_rule_filter = {}
        client.put_bucket_lifecycle_configuration(
            Bucket=bucket,
            LifecycleConfiguration={
                "Rules": [
                    {
                        "Expiration": {"Days": 7},
                        "Filter": auto_expire_rule_filter,
                        "Status": "Enabled",
                    }
                ]
            },
        )

    def check_minio(self):
        # https://min.io/docs/minio/linux/operations/monitoring/healthcheck-probe.html#node-liveness
        livecheck_url = urljoin(settings.AWS_S3_ENDPOINT_URL, "minio/health/live")
        response = httpx.head(livecheck_url)
        try:
            return response.headers["Server"] == "MinIO"
        except KeyError:
            return False
