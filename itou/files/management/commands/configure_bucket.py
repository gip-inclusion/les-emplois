import json
from urllib.parse import urljoin

import httpx
from django.conf import settings

from itou.utils.command import BaseCommand
from itou.utils.enums import ItouEnvironment
from itou.utils.storage.s3 import TEMPORARY_STORAGE_PREFIX, dora_s3_client, pilotage_s3_client, s3_client


BUCKETS = {
    settings.PILOTAGE_DATASTORE_S3_BUCKET_NAME: {
        "client": pilotage_s3_client(),
        "url": settings.PILOTAGE_DATASTORE_S3_ENDPOINT_URL,
        "policy_statements": [
            {
                "Sid": "AllowPublicRead",
                "Effect": "Allow",
                "Principal": {"AWS": "*"},
                "Action": "s3:GetObject",
                "Resource": [
                    f"arn:aws:s3:::{settings.PILOTAGE_DATASTORE_S3_BUCKET_NAME}/*",
                ],
            }
        ],
    },
    settings.DORA_AWS_S3_STORAGE_BUCKET_NAME: {
        "client": dora_s3_client(),
        "url": settings.DORA_AWS_S3_ENDPOINT_URL,
        "policy_statements": [
            {
                "Sid": "AllowPublicRead",
                "Effect": "Allow",
                "Principal": {"AWS": "*"},
                "Action": "s3:GetObject",
                "Resource": [
                    f"arn:aws:s3:::{settings.DORA_AWS_S3_STORAGE_BUCKET_NAME}/*",
                ],
            }
        ],
    },
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


class Command(BaseCommand):
    ATOMIC_HANDLE = False
    AUTO_TRIGGER_CONTEXT = False

    def add_arguments(self, parser):
        parser.add_argument("--auto-expire", action="store_true", dest="autoexpire")

    def handle(self, *args, autoexpire=False, **options):
        for bucket in BUCKETS.keys():
            is_minio = self.check_minio(url=BUCKETS[bucket].get("url"))
            client = BUCKETS[bucket].get("client")

            try:
                client.create_bucket(Bucket=bucket)
            except client.exceptions.BucketAlreadyOwnedByYou:
                pass

            if policy_statements := BUCKETS[bucket].get("policy_statements"):
                client.put_bucket_policy(
                    Bucket=bucket,
                    Policy=json.dumps(
                        {
                            "Version": "2012-10-17",
                            "Statement": policy_statements,
                        }
                    ),
                )

                client.put_bucket_versioning(
                    Bucket=bucket,
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
