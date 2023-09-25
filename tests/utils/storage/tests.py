import pytest
from django.conf import settings
from django.test import TestCase

from itou.utils.storage.s3 import S3Upload


class S3Tests(TestCase):
    def test_generate_form_values(self):
        s3_upload = S3Upload()
        form_values = s3_upload.form_values
        assert form_values.get("url")
        assert form_values.get("fields")
        expected_keys = ["x-amz-algorithm", "x-amz-credential", "x-amz-date", "policy", "x-amz-signature"]
        assert sorted(form_values["fields"].keys()) == sorted(expected_keys)

    def test_get_upload_config(self):
        s3_upload = S3Upload()
        expected_keys = [
            "allowed_mime_types",
            "upload_expiration",
            "key_path",
            "max_files",
            "max_file_size",
            "timeout",
        ]
        assert sorted(expected_keys) == sorted(s3_upload.config.keys())
        for _, value in s3_upload.config.items():
            assert value is not None

        # test presence of default values
        default_settings = settings.STORAGE_UPLOAD_KINDS
        test_resume_settings = default_settings | {"resume": {}}
        with self.settings(STORAGE_UPLOAD_KINDS=test_resume_settings):
            s3_upload_resume = S3Upload(kind="resume")
            assert s3_upload_resume.config["allowed_mime_types"] == "application/pdf"
            assert s3_upload_resume.config["key_path"] == ""
            assert s3_upload_resume.config["upload_expiration"] == 5400
            assert s3_upload_resume.config["max_file_size"] == 5
            assert s3_upload_resume.config["max_files"] == 1

        # Test allowed mime types formatting
        file_type = "application/pdf"
        default_test_settings = default_settings["default"] | {"allowed_mime_types": [file_type]}
        with self.settings(STORAGE_UPLOAD_KINDS={"default": default_test_settings}):
            assert S3Upload().config["allowed_mime_types"] == file_type

        default_test_settings = default_settings["default"] | {"allowed_mime_types": ["application/pdf", "image/jpeg"]}
        with self.settings(STORAGE_UPLOAD_KINDS={"default": default_test_settings}):
            assert S3Upload().config["allowed_mime_types"] == "application/pdf,image/jpeg"

        # Key path should not begin nor end with a slash.
        default_test_settings = default_settings["default"] | {"key_path": "/resume/"}
        with self.settings(STORAGE_UPLOAD_KINDS={"default": default_test_settings}):
            with pytest.raises(ValueError):
                S3Upload()

        # Assert an error is raised if a config is not found.
        with pytest.raises(KeyError):
            S3Upload("teapot")
