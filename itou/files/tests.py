from django.conf import settings
from django.utils import timezone

from itou.approvals.enums import ProlongationReason
from itou.approvals.factories import ProlongationFactory

from .models import File


def test_report_file_link():
    prolongation = ProlongationFactory(reason=ProlongationReason.RQTH)

    assert prolongation.report_file is None

    file_path = "prolongation_report/test.xslx"
    report_file = File(file_path, timezone.now())
    report_file.save()

    prolongation.report_file = report_file
    prolongation.save()

    assert (
        prolongation.report_file.link
        == f"https://{settings.S3_STORAGE_ENDPOINT_DOMAIN}/{settings.S3_STORAGE_BUCKET_NAME}/{file_path}"
    )
