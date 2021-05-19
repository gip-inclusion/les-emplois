"""
Useful functions to interact with an S3 bucket.
"""
import base64
import hashlib
import hmac
import json

from dateutil.relativedelta import relativedelta
from django.conf import settings


def sign(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def sign_to_str(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).hexdigest()


def encode_dict(dict_to_encode):
    json_dump = json.dumps(dict_to_encode).encode("utf-8")
    return base64.b64encode(json_dump).decode("utf-8")


def format_date_short(date):
    """
    Used in the credential URL and in the signature.
    """
    return date.strftime("%Y%m%d")


def format_date_long(date):
    """
    Used in the policy and in the "x-amz-date" form input.
    """
    return date.strftime("%Y%m%dT%H%M%SZ")


def format_expiration_date(date):
    """
    Used in the policy.
    """
    return date.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def generate_credential_url(date):
    """
    Each directory is a key used when generating the signature.
    """
    date_str = format_date_short(date)
    return f"{settings.STORAGE_ACCESS_KEY_ID}/{date_str}/{settings.AWS_S3_REGION_NAME}/s3/aws4_request"


def generate_signature(date, string_to_sign):
    """
    Use credential's URL directories to sign a string.
    """
    date_str = format_date_short(date)
    date_key = sign(("AWS4" + settings.STORAGE_SECRET_ACCESS_KEY).encode("utf-8"), date_str)
    date_region_key = sign(date_key, settings.AWS_S3_REGION_NAME)
    date_region_service_key = sign(date_region_key, "s3")
    signing_key = sign(date_region_service_key, "aws4_request")
    return sign_to_str(key=signing_key, msg=string_to_sign)


def policy_as_dict(date):
    """
    Set uploading file policy. Different from the bucket policy.
    """
    expiration_date = date + relativedelta(hours=1)
    form_credential_url = generate_credential_url(date=date)
    form_date = format_date_long(date)

    policy = {
        "expiration": format_expiration_date(expiration_date),
        "conditions": [
            ["starts-with", "$key", ""],
            {"bucket": settings.STORAGE_BUCKET_NAME},
            {"x-amz-algorithm": "AWS4-HMAC-SHA256"},
            {"x-amz-credential": form_credential_url},
            {"x-amz-date": form_date},
        ],
    }
    return policy


def generate_form_values(date):
    form_date = format_date_long(date)
    policy = policy_as_dict(date)
    encoded_policy = encode_dict(policy)
    form_credential_url = generate_credential_url(date)
    signature = generate_signature(date=date, string_to_sign=encoded_policy)

    return {
        "form_credential_url": form_credential_url,
        "form_date": form_date,
        "encoded_policy": encoded_policy,
        "signature": signature,
    }
