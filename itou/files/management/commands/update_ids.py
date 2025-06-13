import uuid

from django.db import transaction
from django.db.models import F

from itou.antivirus.models import Scan
from itou.approvals.models import Prolongation, ProlongationRequest
from itou.communications.models import AnnouncementItem
from itou.files.models import File
from itou.geiq_assessments.models import Assessment
from itou.job_applications.models import JobApplication
from itou.siae_evaluations.models import EvaluatedAdministrativeCriteria
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    BATCH_SIZE = 500

    def get_relations(self):
        return [
            (JobApplication, "resume"),
            (ProlongationRequest, "report_file"),
            (Prolongation, "report_file"),
            (EvaluatedAdministrativeCriteria, "proof"),
            (Scan, "file"),
            (AnnouncementItem, "image_storage"),
            (Assessment, "summary_document_file"),
            (Assessment, "structure_financial_assessment_file"),
            (Assessment, "action_financial_assessment_file"),
        ]

    def handle(self, *args, **options):
        files = list(File.objects.filter(id=F("key"))[: self.BATCH_SIZE])
        nb = len(files)

        for file in files:
            new_id = str(uuid.uuid4())
            with transaction.atomic():
                for model, field in self.get_relations():
                    field_name = model._meta.get_field(field).attname
                    model.objects.filter(**{field_name: file.id}).update(**{field_name: new_id})
                File.objects.filter(id=file.id).update(id=new_id)

        self.logger.info(f"Updated {nb} files")
