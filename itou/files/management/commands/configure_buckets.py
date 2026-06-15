import json
from urllib.parse import urljoin

import httpx
from django.conf import settings

from itou.utils.command import BaseCommand
from itou.utils.enums import ItouEnvironment
from itou.utils.storage.s3 import TEMPORARY_STORAGE_PREFIX, s3_client


class Command(BaseCommand):
    ATOMIC_HANDLE = False
    AUTO_TRIGGER_CONTEXT = False

    def add_arguments(self, parser):
        parser.add_argument("--auto-expire", action="store_true", dest="autoexpire")

    def get_buckets(self):
        # Some of the following settings are overridden for tests
        buckets = {
            settings.AWS_STORAGE_BUCKET_NAME: {
                "client": s3_client(),
                "url": settings.AWS_S3_ENDPOINT_URL,
                "policy_statements": [
                    # `resume/` is publicly readable during the sunset window so that URLs baked into already-sent
                    # emails and already-returned API responses continue to resolve. New uploads are written to
                    # `resume-private/` (see itou/www/apply/views/submit_views.py), which is never listed here.
                    # Remove `resume/` from this list once `migrate_resume_to_private` has copied every legacy
                    # object into `resume-private/` and the sunset date has passed.
                    {
                        "Sid": "AllowPublicRead",
                        "Effect": "Allow",
                        "Principal": {"AWS": "*"},
                        "Action": "s3:GetObject",
                        "Resource": [
                            f"arn:aws:s3:::{settings.AWS_STORAGE_BUCKET_NAME}/resume/*",
                            f"arn:aws:s3:::{settings.AWS_STORAGE_BUCKET_NAME}/news-images/*",
                        ],
                    }
                ],
            },
        }

        # The environment variables may not be configured in some environments such as DEMO
        buckets = {key: value for key, value in buckets.items() if key}

        return buckets

    def handle(self, *args, autoexpire=False, **options):
        buckets = self.get_buckets()
        for bucket_name, bucket in buckets.items():
            is_minio = self.check_minio(url=bucket.get("url"))
            client = bucket.get("client")

            try:
                client.create_bucket(Bucket=bucket_name)
            except client.exceptions.BucketAlreadyOwnedByYou:
                pass

            if policy_statements := bucket.get("policy_statements"):
                client.put_bucket_policy(
                    Bucket=bucket_name,
                    Policy=json.dumps(
                        {
                            "Version": "2012-10-17",
                            "Statement": policy_statements,
                        }
                    ),
                )

                client.put_bucket_versioning(
                    Bucket=bucket_name,
                    VersioningConfiguration={"Status": "Enabled"},
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
                    Bucket=bucket_name,
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
                Bucket=bucket_name,
                LifecycleConfiguration={
                    "Rules": [
                        {
                            "Expiration": {"Days": 7},
                            "Filter": auto_expire_rule_filter,
                            "Status": "Enabled",
                        },
                        {
                            "Prefix": "",
                            "Expiration": {"ExpiredObjectDeleteMarker": True},
                            "Status": "Enabled",
                        },
                        {
                            "Prefix": "",
                            "NoncurrentVersionExpiration": {"NoncurrentDays": 365},
                            "Status": "Enabled",
                        },
                    ]
                },
            )

    def check_minio(self, url):
        # https://min.io/docs/minio/linux/operations/monitoring/healthcheck-probe.html#node-liveness
        livecheck_url = urljoin(url, "minio/health/live")
        response = httpx.head(livecheck_url)
        try:
            return response.headers["Server"] == "MinIO"
        except KeyError:
            return False
