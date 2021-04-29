import base64
import datetime
import hmac
import json

from django.test import SimpleTestCase, override_settings

from itou.utils.storage import s3


class S3Tests(SimpleTestCase):
    def test_sign(self):
        # Amazon V4 signature.
        # See https://docs.aws.amazon.com/AmazonS3/latest/API/sigv4-authentication-HTTPPOST.html
        result = s3.sign(key="key", msg="Les carottes sont cuites.")
        expected = b"\xf7\x12\xcd\x1b\x91xN\xb5\x9e\xde\xf4\x9d\xf3G\x98)"
        expected += b"^\xecq\x03\x99\x15\xc01>\x12\xa4\xeeTy\x07\x9b"
        self.assertTrue(isinstance(result, bytes))
        self.assertEqual(result, expected)

    def test_sign_to_str(self):
        result = s3.sign_to_str(key="key", msg="Le loup est dans la charette.")
        expected = "bdcbaf90073d958b4b8b98cdbd22ccbbecf72eebd5c7633855d0b058ffd4c1a8"
        self.assertTrue(isinstance(result, str))
        self.assertEqual(result, expected)

    def test_encode_dict(self):
        # Must be base64 encoded.
        fruits = {"exotic": ["bananas"]}
        encoded_result = s3.encode_dict(fruits)
        decoded_result = json.loads(base64.b64decode(encoded_result))
        self.assertTrue(isinstance(encoded_result, str))
        self.assertEqual(encoded_result, "eyJleG90aWMiOiBbImJhbmFuYXMiXX0=")
        self.assertEqual(fruits, decoded_result)

    def test_generate_credential_url(self):
        date = datetime.datetime(2021, 4, 29)
        access_key_id = "A1234567890"
        region_name = "eu-west-4"
        with self.settings(STORAGE_ACCESS_KEY_ID=access_key_id, AWS_S3_REGION_NAME=region_name):
            self.assertEqual(
                s3.generate_credential_url(date=date), f"{access_key_id}/20210429/{region_name}/s3/aws4_request"
            )

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
            form_credential_url = s3.generate_credential_url(date)
            # TODO: test dynamic expiration date
            expected_policy = {
                "expiration": "2021-04-29T13:13:14.155Z",
                "conditions": [
                    {"bucket": test_settings["STORAGE_BUCKET_NAME"]},
                    {"x-amz-algorithm": "AWS4-HMAC-SHA256"},
                    {"x-amz-credential": form_credential_url},
                    {"x-amz-date": "20210429T121314Z"},
                ],
            }
            policy = s3.policy_as_dict(date)
            self.assertTrue(policy.keys() == expected_policy.keys())
            for item in expected_policy["conditions"]:
                self.assertTrue(item in policy["conditions"])

    def test_generate_form_values(self):
        date = datetime.datetime(2021, 4, 29, 12, 13, 14, 155)
        form_values = s3.generate_form_values(date)
        expected_keys = ["form_credential_url", "form_date", "encoded_policy", "signature"]
        self.assertEqual(sorted(form_values.keys()), sorted(expected_keys))
        self.assertEqual(form_values["form_date"], "20210429T121314Z")
