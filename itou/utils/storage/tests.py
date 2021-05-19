import base64
import datetime
import json

from django.conf import settings
from django.test import SimpleTestCase

from itou.utils.storage.s3 import S3Upload


class S3Tests(SimpleTestCase):
    def test_sign_to_bytes(self):
        # Amazon V4 signature.
        # See https://docs.aws.amazon.com/AmazonS3/latest/API/sigv4-authentication-HTTPPOST.html
        result = S3Upload.sign_to_bytes(key="key", msg="Les carottes sont cuites.")
        expected = b"\xf7\x12\xcd\x1b\x91xN\xb5\x9e\xde\xf4\x9d\xf3G\x98)"
        expected += b"^\xecq\x03\x99\x15\xc01>\x12\xa4\xeeTy\x07\x9b"
        self.assertTrue(isinstance(result, bytes))
        self.assertEqual(result, expected)

    def test_sign_to_string(self):
        result = S3Upload.sign_to_string(key="key", msg="Le loup est dans la charette.")
        expected = "bdcbaf90073d958b4b8b98cdbd22ccbbecf72eebd5c7633855d0b058ffd4c1a8"
        self.assertTrue(isinstance(result, str))
        self.assertEqual(result, expected)

    def test_encode_dict(self):
        # Must be base64 encoded.
        fruits = {"exotic": ["bananas"]}
        encoded_result = S3Upload.encode_dict(fruits)
        decoded_result = json.loads(base64.b64decode(encoded_result))
        self.assertTrue(isinstance(encoded_result, str))
        self.assertEqual(encoded_result, "eyJleG90aWMiOiBbImJhbmFuYXMiXX0=")
        self.assertEqual(fruits, decoded_result)

    def test_generate_credential_url(self):
        date = datetime.datetime(2021, 4, 29)
        access_key_id = "A1234567890"
        region_name = "eu-west-4"
        with self.settings(STORAGE_ACCESS_KEY_ID=access_key_id, AWS_S3_REGION_NAME=region_name):
            s3_upload = S3Upload(date=date)
            self.assertEqual(s3_upload.credential_url, f"{access_key_id}/20210429/{region_name}/s3/aws4_request")

    def test_generate_signature(self):
        # Not sure how to test this...
        # hmac.compare_digest(calculated_signature, signature_to_verify)
        pass

    def test_policy_as_dict(self):
        """
        Test required keys only.
        """
        date = datetime.datetime(2021, 4, 29, 12, 13, 14, 155)
        test_settings = {
            "STORAGE_ACCESS_KEY_ID": "A1234567890",
            "STORAGE_BUCKET_NAME": "nemos-bucket",
            "AWS_S3_REGION_NAME": "eu-west-4",
        }
        with self.settings(**test_settings):
            s3_upload = S3Upload(date=date)
            credential_url = s3_upload.credential_url
            result = s3_upload.policy_as_dict()
            expected = {
                "expiration": "2021-04-29T13:13:14.000Z",
                "conditions": [
                    {"bucket": test_settings["STORAGE_BUCKET_NAME"]},
                    {"x-amz-algorithm": "AWS4-HMAC-SHA256"},
                    {"x-amz-credential": credential_url},
                    {"x-amz-date": "20210429T121314Z"},
                ],
            }

            for item in expected["conditions"]:
                self.assertIn(item, result["conditions"])

            # test expiration formatting
            self.assertEqual(expected["expiration"], result["expiration"])

            # test key path condition
            expected = {"conditions": ["starts-with", "$key", ""]}
            self.assertEqual(result["conditions"][0], expected["conditions"])

    def test_generate_form_values(self):
        date = datetime.datetime(2021, 4, 29, 12, 13, 14, 155)
        s3_upload = S3Upload(date=date)
        form_values = s3_upload.form_values
        expected_keys = ["credential_url", "date", "encoded_policy", "signature", "endpoint"]
        self.assertEqual(sorted(form_values.keys()), sorted(expected_keys))
        self.assertEqual(form_values["date"], "20210429T121314Z")

    def test_get_upload_config(self):
        s3_upload = S3Upload()
        result = s3_upload.config
        expected_keys = [
            "allowed_mime_types",
            "upload_expiration",
            "key_path",
            "max_files",
            "max_file_size",
            "timeout",
        ]
        self.assertEqual(sorted(expected_keys), sorted(result.keys()))
        for _, value in result.items():
            self.assertIsNot(value, None)

        # test presence of default values
        default_settings = settings.STORAGE_UPLOAD_KINDS
        test_resume_settings = default_settings | {"resume": {}}
        with self.settings(STORAGE_UPLOAD_KINDS=test_resume_settings):
            s3_upload_resume = S3Upload(kind="resume")
            result = s3_upload_resume.config
            self.assertEqual(result["allowed_mime_types"], "*")
            self.assertEqual(result["key_path"], "")
            self.assertEqual(result["upload_expiration"], 1)
            self.assertEqual(result["max_file_size"], 5)
            self.assertEqual(result["max_files"], 3)

        # Test allowed mime types formatting
        file_type = "application/pdf"
        default_test_settings = default_settings["default"] | {"allowed_mime_types": [file_type]}
        with self.settings(STORAGE_UPLOAD_KINDS={"default": default_test_settings}):
            s3_upload = S3Upload()
            result = s3_upload.config["allowed_mime_types"]
            self.assertEqual(result, file_type)

        default_test_settings = default_settings["default"] | {"allowed_mime_types": ["application/pdf", "image/jpeg"]}
        with self.settings(STORAGE_UPLOAD_KINDS={"default": default_test_settings}):
            s3_upload = S3Upload()
            result = s3_upload.config["allowed_mime_types"]
            self.assertEqual(result, "application/pdf,image/jpeg")

        # Key path should not begin nor end with a slash.
        default_test_settings = default_settings["default"] | {"key_path": "/resume/"}
        with self.settings(STORAGE_UPLOAD_KINDS={"default": default_test_settings}):
            with self.assertRaises(ValueError):
                S3Upload()

        # Assert an error is raised if a config is not found.
        with self.assertRaises(KeyError):
            S3Upload("teapot")
