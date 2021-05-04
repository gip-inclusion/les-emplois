"""
Useful functions to interact with an S3 bucket.
"""
import base64
import hashlib
import hmac
import json
from datetime import timedelta

from django.conf import settings
from django.utils import timezone


class S3Upload:
    def __init__(self, kind="default", date=None):
        self.date = date or timezone.now()
        self.config = self.get_config(kind)

    def generate_signature(self, string_to_sign):
        """
        Use credential's URL directories to sign a string.
        """
        date_str = self.format_date_short(self.date)
        date_key = self.sign_to_bytes(("AWS4" + settings.STORAGE_SECRET_ACCESS_KEY), date_str)
        date_region_key = self.sign_to_bytes(date_key, settings.AWS_S3_REGION_NAME)
        date_region_service_key = self.sign_to_bytes(date_region_key, "s3")
        signing_key = self.sign_to_bytes(date_region_service_key, "aws4_request")
        return self.sign_to_string(key=signing_key, msg=string_to_sign)

    def policy_as_dict(self):
        """
        Set uploading file policy. Different from the bucket policy.
        """
        form_date = self.format_date_long(self.date)
        expiration_date = self.format_expiration_date(self.form_expires_at)
        bucket_name = settings.STORAGE_BUCKET_NAME
        key_path = self.config["key_path"]

        policy = {
            "expiration": expiration_date,
            "conditions": [
                ["starts-with", "$key", key_path],
                {"bucket": bucket_name},
                {"x-amz-algorithm": "AWS4-HMAC-SHA256"},
                {"x-amz-credential": self.credential_url},
                {"x-amz-date": form_date},
            ],
        }
        return policy

    @property
    def credential_url(self):
        """
        Each directory is a key used when generating the signature.
        """
        date_str = self.format_date_short(self.date)
        return f"{settings.STORAGE_ACCESS_KEY_ID}/{date_str}/{settings.AWS_S3_REGION_NAME}/s3/aws4_request"

    @property
    def form_expires_at(self):
        return self.date + timedelta(hours=self.config["upload_expiration"])

    @property
    def form_values(self):
        form_date = self.format_date_long(self.date)
        policy = self.policy_as_dict()
        encoded_policy = self.encode_dict(policy)
        credential_url = self.credential_url
        signature = self.generate_signature(string_to_sign=encoded_policy)

        return {
            "credential_url": credential_url,
            "date": form_date,
            "encoded_policy": encoded_policy,
            "signature": signature,
            "endpoint": settings.AWS_S3_BUCKET_ENDPOINT_URL,
        }

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

    @staticmethod
    def sign_to_bytes(key, msg):
        if isinstance(key, str):
            key = key.encode("utf-8")
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    @staticmethod
    def sign_to_string(key, msg):
        if isinstance(key, str):
            key = key.encode("utf-8")
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def encode_dict(dict_to_encode):
        json_dump = json.dumps(dict_to_encode).encode("utf-8")
        return base64.b64encode(json_dump).decode("utf-8")

    @staticmethod
    def format_date_short(date):
        """
        Used in the credential URL and in the signature.
        """
        return date.strftime("%Y%m%d")

    @staticmethod
    def format_date_long(date):
        """
        Used in the policy and in the "x-amz-date" form input.
        """
        return date.strftime("%Y%m%dT%H%M%SZ")

    @staticmethod
    def format_expiration_date(date):
        """
        Used in the policy.
        """
        return date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
