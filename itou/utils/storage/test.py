from django.test import override_settings

from itou.utils.test import TestCase


# The apply tests do use the S3 resource since part of the process consists in uploading a document.
@override_settings(
    S3_STORAGE_ENDPOINT_DOMAIN="server.com",
    S3_STORAGE_BUCKET_NAME="foobar",
    S3_STORAGE_BUCKET_REGION="us-east-1",
    S3_STORAGE_ACCESS_KEY_ID="key",
    S3_STORAGE_SECRET_ACCESS_KEY="secret",
)
class S3AccessingTestCase(TestCase):
    pass
