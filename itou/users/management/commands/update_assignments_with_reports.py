import time

from django.db import transaction

from itou.companies.models import ProSupportReport
from itou.users.enums import ActionKind
from itou.users.models import JobSeekerAssignment
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    help = "Update job seeker assignments with pro support reports filled."

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

        count_created = count_updated = 0
        reports = (
            ProSupportReport.objects.all()
            .order_by("job_seeker", "author", "company", "-created_at")
            .distinct("job_seeker", "author", "company")
        )  # an employer is unlikely to have filled more than one report, but better safe than sorry

        with transaction.atomic():
            assignments_qs = JobSeekerAssignment.objects.filter(
                job_seeker__in=reports.values_list("job_seeker_id")
            ).select_for_update(of=("self",), no_key=True)

            self.logger.info(f"Found {len(assignments_qs)} assignments of job seekers associated to existing reports.")

            assignments = {(a.job_seeker_id, a.professional_id, a.company_id): a for a in assignments_qs}
            assignments_to_create = []
            assignments_to_update = []

            for report in reports:
                key = (report.job_seeker_id, report.author_id, report.company_id)
                if assignment := assignments.get(key):
                    if assignment.last_action_at < report.created_at:
                        assignment.last_action_at = report.created_at
                        assignment.last_action_kind = ActionKind.FILL_REPORT
                        assignments_to_update.append(assignment)
                        count_updated += 1
                else:
                    assignments_to_create.append(
                        JobSeekerAssignment(
                            job_seeker=report.job_seeker,
                            professional=report.author,
                            company=report.company,
                            last_action_at=report.created_at,
                            last_action_kind=ActionKind.FILL_REPORT,
                        )
                    )
                    count_created += 1

            if wet_run:
                JobSeekerAssignment.objects.bulk_create(assignments_to_create)
                JobSeekerAssignment.objects.bulk_update(
                    assignments_to_update, fields=["last_action_at", "last_action_kind"]
                )
            self.logger.info("Elapsed time: %0.2f seconds", time.perf_counter() - start_time)

        self.logger.info(f"Created {count_created} assignments")
        self.logger.info(f"Updated {count_updated} assignments")
