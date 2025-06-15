import datetime
import functools
import operator
from itertools import batched

from django.db import transaction
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
        print("looking for valid files")
        linked_files_pks = functools.reduce(
            operator.or_,
            [
                set(model.objects.exclude(**{field: None}).values_list(field, flat=True))
                for model, field in self.get_relations()
            ],
        )
        print(f" -> found {len(linked_files_pks)}")
        print("looking for orphan files")
        to_delete_pks = list(
            File.objects.filter(
                last_modified__lte=timezone.now() - datetime.timedelta(days=1),
            )
            .exclude(pk__in=linked_files_pks)
            .values_list("pk", flat=True)
        )
        print(f" -> found {len(to_delete_pks)}")

        total = 0
        for batch_pks in batched(to_delete_pks, 10_000):
            with transaction.atomic():
                deleted = File.objects.filter(pk__in=batch_pks).delete()
                total += deleted[1]["files.File"]
                self.logger.info(deleted)
        self.logger.info(f"Deleted {total} orphans files without purging file from S3")
