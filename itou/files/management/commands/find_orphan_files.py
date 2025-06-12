import datetime
import functools
import operator

from django.utils import timezone

from itou.approvals.models import Prolongation, ProlongationRequest
from itou.communications.models import AnnouncementItem
from itou.files.models import File
from itou.geiq_assessments.models import Assessment
from itou.job_applications.models import JobApplication
from itou.siae_evaluations.models import EvaluatedAdministrativeCriteria
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    def get_relations(self):
        # Don't look at Scans FK
        return [
            (JobApplication, "resume"),
            (ProlongationRequest, "report_file"),
            (Prolongation, "report_file"),
            (EvaluatedAdministrativeCriteria, "proof"),
            (AnnouncementItem, "image_storage"),
            (Assessment, "summary_document_file"),
            (Assessment, "structure_financial_assessment_file"),
            (Assessment, "action_financial_assessment_file"),
        ]

    def handle(self, *args, **options):
        linked_files_pks = functools.reduce(
            operator.or_,
            [
                set(model.objects.exclude(**{field: None}).values_list(field, flat=True))
                for model, field in self.get_relations()
            ],
        )
        updated = (
            File.objects.filter(
                deleted_at=None,
                last_modified__lte=timezone.now() - datetime.timedelta(days=1),
            )
            .exclude(pk__in=linked_files_pks)
            .update(deleted_at=timezone.now())
        )
        self.logger.info(f"Marked {updated} orphans files for deletion")
