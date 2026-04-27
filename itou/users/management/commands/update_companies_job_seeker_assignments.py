import time
from itertools import batched
from math import ceil

from django.db import transaction

from itou.companies.models import Company
from itou.users.enums import ActionKind
from itou.users.models import JobSeekerAssignment
from itou.utils.command import BaseCommand


CHUNK_SIZE = 1000


class Command(BaseCommand):
    help = "Update existing job seeker assignments between job seekers and employers."

    ATOMIC_HANDLE = False
    AUTO_TRIGGER_CONTEXT = False

    def add_arguments(self, parser):
        parser.add_argument(
            "--wet-run",
            dest="wet_run",
            action="store_true",
            help="Effectively update the assignments in the database.",
        )

    def handle(self, wet_run=False, **options):
        start_time = time.perf_counter()
        self.logger.info("Script starting!")

        # Identify work to do for efficient batching.
        job_seeker_assignments_pks = (
            Company.objects.prefetch_related("company_assignments")
            .filter(company_assignments__last_action_kind__in=[ActionKind.ACCEPT, ActionKind.HIRE])
            .order_by("company_assignments__pk")
            .values_list("company_assignments__pk", flat=True)
        )

        self.logger.info(f"{len(job_seeker_assignments_pks)} JobSeekerAssignment to update.")
        chunks_total = ceil(len(job_seeker_assignments_pks) / CHUNK_SIZE)
        count_updated = 0

        chunks_count = 0
        for chunks_count, assignments_pks in enumerate(batched(job_seeker_assignments_pks, CHUNK_SIZE)):
            with transaction.atomic():
                assignments = JobSeekerAssignment.objects.filter(pk__in=assignments_pks).select_for_update(
                    of=("self",), no_key=True
                )

                assignments_to_update = []

                for assignment in assignments:
                    assignment.assigned_to_unknown_advisor = True
                    assignments_to_update.append(assignment)

                count_updated += len(assignments_to_update)
                if wet_run:
                    JobSeekerAssignment.objects.bulk_update(
                        assignments_to_update, fields=["assigned_to_unknown_advisor"]
                    )

                print(
                    f"{chunks_count / chunks_total * 100:.2f}% - "
                    f"elapsed time: {time.perf_counter() - start_time:.2f}s",
                    end="\r",
                )
        print(f"Updated {count_updated} assignments")
