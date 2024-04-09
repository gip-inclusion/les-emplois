import time

from django.core.management.base import BaseCommand

from itou.approvals.models import Approval
from itou.job_applications.enums import JobApplicationState


BATCH_SIZE = 1000


class Command(BaseCommand):
    def handle(self, **options):
        objects_to_migrate = Approval.objects.filter(
            origin_sender_kind=None,
            jobapplication__state=JobApplicationState.ACCEPTED,
        ).distinct()
        total_objects = objects_to_migrate.count()
        print(f"Before: {total_objects}")

        batch = []
        for approval in objects_to_migrate.only("pk").iterator():
            origin_job_application = (
                approval.jobapplication_set.accepted()
                .select_related("sender_prescriber_organization", "to_company")
                .earliest("created_at")
            )
            for key, value in approval.get_origin_kwargs(origin_job_application).items():
                setattr(approval, key, value)
            batch.append(approval)
            if len(batch) >= min(BATCH_SIZE, total_objects):
                Approval.objects.bulk_update(
                    batch,
                    fields=[
                        "origin_siae_siret",
                        "origin_siae_kind",
                        "origin_sender_kind",
                        "origin_prescriber_organization_kind",
                    ],
                )
                batch = []
                print(f"Remaining: {objects_to_migrate.count()}")
                time.sleep(1)

        print(f"After: {objects_to_migrate.count()}")
