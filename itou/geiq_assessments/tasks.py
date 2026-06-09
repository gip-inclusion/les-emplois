import logging
import uuid

from django.core.cache import caches
from django.core.files.base import ContentFile
from huey.contrib.djhuey import db_task

from itou.files.models import save_file
from itou.geiq_assessments.models import Assessment
from itou.utils.apis import geiq_label


logger = logging.getLogger(__name__)


# Label API client method used to retrieve each file for a given GEIQ.
SYNC_FILE_API_METHOD = {
    "summary_document_file": "get_synthese_pdf",
    "structure_financial_assessment_file": "get_compte_pdf",
}

# How long the retrieval lock is held.
SYNC_FILE_LOCK_TTL = 60
# How long we remember retrieval has failed for a given file.
SYNC_FILE_ERROR_CACHE_TTL = 3 * 60


def file_error_cache_key(assessment_pk, file_field):
    return f"geiq-assessment-sync-file-error:{assessment_pk}:{file_field}"


def file_sync_lock_key(assessment_pk, file_field):
    return f"geiq-assessment-sync-file-lock:{assessment_pk}:{file_field}"


@db_task()
def sync_assessment_file(assessment_pk, *, file_field):
    cache = caches["failsafe"]
    # We avoid fetching the same PDF twice.
    lock = cache.lock(file_sync_lock_key(assessment_pk, file_field), timeout=SYNC_FILE_LOCK_TTL)
    if not lock.acquire(blocking=False):
        return  # Another task is already retrieving this file.
    try:
        assessment = Assessment.objects.get(pk=assessment_pk)
        if getattr(assessment, file_field):
            return  # Nothing to do: the file has already been retrieved.
        client = geiq_label.get_client()
        pdf_content = getattr(client, SYNC_FILE_API_METHOD[file_field])(geiq_id=assessment.label_geiq_id)
        file = save_file(
            folder="geiq-assessments/",
            file=ContentFile(content=pdf_content, name=f"{uuid.uuid4()}.pdf"),
            anonymize_filename=False,
        )
        setattr(assessment, file_field, file)
        assessment.save(update_fields=(file_field,))
        logger.info(f"File added to assessment {assessment_pk}: {file_field}")
    except Exception as e:
        logger.exception(
            "Failed to retrieve a PDF from the Label API "
            f"(assessment={str(assessment_pk)} field={file_field}): {e.__class__.__name__}"
        )
        cache.set(file_error_cache_key(assessment_pk, file_field), True, SYNC_FILE_ERROR_CACHE_TTL)
    finally:
        lock.release()
