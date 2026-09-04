import time

from django.db import transaction

from itou.insertion.models import Orientation
from itou.users.enums import ActionKind
from itou.users.models import JobSeekerAssignment
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    help = "Update existing job seekers assignments with orientations."

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

        count_created = 0
        count_updated = 0
        # there are about ~100 orientations only
        orientations = (
            Orientation.objects.all()
            .order_by(
                "beneficiary",
                "sender",
                "sender_prescriber_organization",
                "sender_company",
                "-created_at",
            )
            .distinct("beneficiary", "sender", "sender_prescriber_organization", "sender_company")
        )  # keep only the last orientation sent by a sender for a given beneficiary

        with transaction.atomic():
            # Filter existing assignments based on job seekers
            assignments_qs = JobSeekerAssignment.objects.filter(
                job_seeker__in=orientations.values_list("beneficiary_id")
            ).select_for_update(of=("self",), no_key=True)
            self.logger.info(
                f"Found {len(assignments_qs)} assignments of job seekers associated to existing orientations."
            )
            assignments = {
                (a.job_seeker_id, a.professional_id, a.prescriber_organization_id, a.company_id): a
                for a in assignments_qs
            }

            assignments_to_update = []
            assignments_to_create = []
            for orientation in orientations:
                key = (
                    orientation.beneficiary_id,
                    orientation.sender_id,
                    orientation.sender_prescriber_organization_id,
                    orientation.sender_company_id,
                )
                if assignment := assignments.get(key):
                    if assignment.last_action_at < orientation.created_at:
                        assignment.last_action_kind = ActionKind.ORIENT
                        assignment.last_action_at = orientation.created_at
                        assignments_to_update.append(assignment)
                        count_updated += 1
                else:
                    assignments_to_create.append(
                        JobSeekerAssignment(
                            job_seeker=orientation.beneficiary,
                            professional=orientation.sender,
                            prescriber_organization=orientation.sender_prescriber_organization,
                            company=orientation.sender_company,
                            last_action_kind=ActionKind.ORIENT,
                            last_action_at=orientation.created_at,
                        )
                    )
                    count_created += 1

            if wet_run:
                JobSeekerAssignment.objects.bulk_create(assignments_to_create)
                JobSeekerAssignment.objects.bulk_update(
                    assignments_to_update, fields=["last_action_kind", "last_action_at"]
                )

            print(
                f"Elapsed time: {time.perf_counter() - start_time:.2f}s",
                end="\r",
            )
        print(f"Created {count_created} assignments")
        print(f"Updated {count_updated} assignments")
