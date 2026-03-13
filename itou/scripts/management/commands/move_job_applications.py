from django.contrib.admin import models as admin_models
from itoutils.django.commands import dry_runnable

from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        parser.add_argument("prescriber", type=int, help="PK of the prescriber")
        parser.add_argument(
            "--from-org",
            required=True,
            type=int,
            help="PK of origin",
        )
        parser.add_argument(
            "--to-org",
            required=True,
            type=int,
            help="PK of destination",
        )
        parser.add_argument(
            "--on-behalf-of",
            required=True,
            type=int,
            help="PK of the user doing the action",
        )
        parser.add_argument("--wet-run", action="store_true", dest="wet_run")

    @dry_runnable
    def handle(self, prescriber, *, from_org, to_org, on_behalf_of, **options):
        self.logger.info(
            "Moving job applications for prescriber=%s from pk=%s to pk=%s for staff=%s",
            prescriber,
            from_org,
            to_org,
            on_behalf_of,
        )
        prescriber = User.objects.get(
            pk=prescriber, kind=UserKind.PRESCRIBER
        )  # Limit to prescriber because of the non-polymorphic model fields
        staff = User.objects.get(pk=on_behalf_of, kind=UserKind.ITOU_STAFF)

        job_applications = (
            prescriber.job_applications_sent.filter(sender_prescriber_organization=from_org)
            .prefetch_related("eligibility_diagnosis")
            .all()
        )
        self.logger.info("Job applications sent by the prescriber count=%s", len(job_applications))
        eligibility_diagnosis = prescriber.eligibilitydiagnosis_set.filter(
            author_prescriber_organization=from_org, jobapplication__in=job_applications
        ).distinct()
        self.logger.info("Eligibility diagnosis created by the prescriber count=%s", len(eligibility_diagnosis))

        # Create log entries and related objects before updating the data so the queryset is not empty
        log_entries = admin_models.LogEntry.objects.log_actions(
            user_id=staff.pk,
            queryset=eligibility_diagnosis,
            action_flag=admin_models.CHANGE,
            change_message=f"author_prescriber_organization from {from_org} to {to_org}",
            single_object=False,
        )
        self.logger.info("Created log entries for eligibility diagnosis count=%s", len(log_entries))
        updated = eligibility_diagnosis.update(author_prescriber_organization=to_org)
        self.logger.info("Updated eligibility diagnosis count=%s", updated)

        # Then the job applications
        log_entries = admin_models.LogEntry.objects.log_actions(
            user_id=staff.pk,
            queryset=job_applications,
            action_flag=admin_models.CHANGE,
            change_message=f"sender_prescriber_organization from {from_org} to {to_org}",
            single_object=False,
        )
        self.logger.info("Created log entries for job applications count=%s", len(log_entries))
        updated = job_applications.update(sender_prescriber_organization=to_org)
        self.logger.info("Updated job applications count=%s", updated)
