import pytest
from django.core.cache import caches
from django.core.files.storage import default_storage

from itou.geiq_assessments import tasks
from tests.files.factories import FileFactory
from tests.geiq_assessments.factories import AssessmentFactory
from tests.utils.testing import default_storage_ls_files


@pytest.fixture
def label_settings(settings):
    settings.API_GEIQ_LABEL_BASE_URL = "https://geiq.label"
    settings.API_GEIQ_LABEL_TOKEN = "S3cr3t!"
    return settings


class TestSyncAssessmentFile:
    @pytest.mark.usefixtures("temporary_bucket")
    def test_success(self, pdf_file, respx_mock, label_settings):
        pdf_file_content = pdf_file.read()
        assessment = AssessmentFactory()
        respx_mock.get(
            f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/SynthesePDF?id={assessment.label_geiq_id}"
        ).respond(
            200,
            content=pdf_file_content,
            headers={
                "content-length": str(len(pdf_file_content)),
                "content-transfer-encoding": "binary",
                "content-type": "application/pdf",
            },
        )

        tasks.sync_assessment_file(assessment.pk, file_field="summary_document_file")

        assessment.refresh_from_db()
        assert assessment.summary_document_file is not None
        assert len(default_storage_ls_files("geiq-assessments")) == 1
        with default_storage.open(assessment.summary_document_file.key) as f:
            assert f.read() == pdf_file_content
        assert caches["failsafe"].get(tasks.file_error_cache_key(assessment.pk, "summary_document_file")) is None

    def test_failure_error_key_in_cache(self, settings):
        settings.API_GEIQ_LABEL_TOKEN = None  # Client initialization will fail.
        assessment = AssessmentFactory()

        tasks.sync_assessment_file(assessment.pk, file_field="summary_document_file")

        assessment.refresh_from_db()
        assert assessment.summary_document_file is None
        assert caches["failsafe"].get(tasks.file_error_cache_key(assessment.pk, "summary_document_file")) is True

    def test_skips_retrieval_when_a_concurrent_task_holds_the_lock(self, settings):
        settings.API_GEIQ_LABEL_TOKEN = None  # Would raise an error if the API was actually called.
        assessment = AssessmentFactory()
        lock = caches["failsafe"].lock(tasks.file_sync_lock_key(assessment.pk, "summary_document_file"))
        assert lock.acquire(blocking=False)
        try:
            tasks.sync_assessment_file(assessment.pk, file_field="summary_document_file")
        finally:
            lock.release()

        assessment.refresh_from_db()
        assert assessment.summary_document_file is None
        # Skipping is not a failure: error is not stored in cache.
        assert caches["failsafe"].get(tasks.file_error_cache_key(assessment.pk, "summary_document_file")) is None

    def test_does_nothing_when_file_already_present(self, settings):
        settings.API_GEIQ_LABEL_TOKEN = None  # Would raise an error if the API was actually called.
        existing_file = FileFactory()
        assessment = AssessmentFactory(summary_document_file=existing_file)

        tasks.sync_assessment_file(assessment.pk, file_field="summary_document_file")

        assessment.refresh_from_db()
        assert assessment.summary_document_file == existing_file
        assert caches["failsafe"].get(tasks.file_error_cache_key(assessment.pk, "summary_document_file")) is None
