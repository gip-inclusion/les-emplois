import logging

from django.conf import settings
from django.contrib.postgres.aggregates import ArrayAgg
from django.db.models import Exists, OuterRef, Q

from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.job_applications import enums as job_applications_enums
from itou.job_applications.models import JobApplication, JobApplicationState
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.command import BaseCommand
from itou.utils.iterators import chunks


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Create follow up groups and add beneficiaries."

    def add_arguments(self, parser):
        parser.add_argument(
            "--wet-run",
            dest="wet_run",
            action="store_true",
            help="Effectively create the groups in the database",
        )
        parser.add_argument(
            "--verbose",
            dest="verbose",
            action="store_true",
            help="Verbose mode",
        )

    def handle(self, wet_run=False, verbose=False, **options):
        objects_created_by = User.objects.get(email=settings.GPS_GROUPS_CREATED_BY_EMAIL)
        logger.info(f"Script starting! 🚀 Memberships will be created by {objects_created_by}.")
        job_applications = JobApplication.objects.exclude(
            state=job_applications_enums.JobApplicationState.NEW,
        ).filter(job_seeker__follow_up_group__isnull=True)

        # Job seekers with a least one job application not new
        # and without a follow up group.
        beneficiaries_without_group_ids = list(
            User.objects.filter(kind=UserKind.JOB_SEEKER, follow_up_group__isnull=True)
            .filter(
                Exists(
                    JobApplication.objects.filter(job_seeker_id=OuterRef("pk")).exclude(state=JobApplicationState.NEW)
                ),
            )
            .values_list("pk", flat=True)
        )

        logger.info(f"Job applications: {job_applications.count()}.")
        logger.info(f"Groups to be created: {len(beneficiaries_without_group_ids)}.")

        for beneficiaries_ids in chunks(beneficiaries_without_group_ids, 1000):
            job_applications_filters = ~Q(job_applications__sender__kind=UserKind.JOB_SEEKER) & ~Q(
                job_applications__state=JobApplicationState.NEW
            )
            beneficiaries_qs = (
                User.objects.filter(pk__in=beneficiaries_ids)
                .annotate(
                    job_apps_senders_ids=ArrayAgg(
                        "job_applications__sender_id",
                        filter=job_applications_filters & ~Q(job_applications__sender=None),
                        distinct=True,
                    )
                )
                .annotate(
                    geiq_diagnosis_authors_ids=ArrayAgg(
                        "geiq_eligibility_diagnoses__author_id",
                        distinct=True,
                    )
                )
                .annotate(
                    accepted_by_ids=ArrayAgg(
                        "job_applications__logs__user_id",
                        filter=Q(job_applications__logs__to_state=JobApplicationState.ACCEPTED)
                        & ~Q(job_applications__logs__user=None),
                        distinct=True,
                    )
                )
                .annotate(
                    eligibility_diagnoses_authors=ArrayAgg(
                        "eligibility_diagnoses__author_id",
                        distinct=True,
                    )
                )
            )
            # Freeze partners annotation before creating groups.
            beneficiaries_with_partners = list(
                beneficiaries_qs.values_list(
                    "id",
                    "job_apps_senders_ids",
                    "geiq_diagnosis_authors_ids",
                    "accepted_by_ids",
                    "eligibility_diagnoses_authors",
                )
            )
            beneficiaries_to_partners = {}
            for (
                beneficiary_id,
                job_apps_senders_ids,
                geiq_diagnosis_author_ids,
                accepted_by_ids,
                eligibility_diagnoses_authors,
            ) in beneficiaries_with_partners:
                partners = set()

                if job_apps_senders_ids:
                    partners |= set(job_apps_senders_ids)
                if geiq_diagnosis_author_ids:
                    partners |= set(geiq_diagnosis_author_ids)
                if accepted_by_ids:
                    partners |= set(accepted_by_ids)
                if eligibility_diagnoses_authors:
                    partners |= set(eligibility_diagnoses_authors)
                # Remove empty values
                partners.discard(None)
                beneficiaries_to_partners[beneficiary_id] = list(partners)

            # Create empty groups.
            groups_to_create = []
            memberships_to_create = []
            empty_groups_counter = 0

            for beneficiary_id, beneficiary_partners in beneficiaries_to_partners.items():
                if not beneficiary_partners:
                    if verbose:
                        logger.info("No partners for %s", beneficiary_id)
                    empty_groups_counter += 1
                    continue
                if verbose:
                    logger.info("creating group for %s with partners=%s", beneficiary_id, beneficiary_partners)
                group = FollowUpGroup(beneficiary_id=beneficiary_id)
                groups_to_create.append(group)
                memberships_to_create += [
                    FollowUpGroupMembership(
                        is_referent=False,
                        member_id=partner_id,
                        creator_id=objects_created_by.id,
                        follow_up_group=group,
                    )
                    for partner_id in beneficiary_partners
                ]

            logger.info(f"Empty groups not created: {empty_groups_counter}.")
            if wet_run:
                logger.info(f"Creating {len(groups_to_create)} FollowUpGroups.")

                FollowUpGroup.objects.bulk_create(groups_to_create)

                logger.info(f"Creating {len(memberships_to_create)} FollowUpGroupMembership.")
                FollowUpGroupMembership.objects.bulk_create(memberships_to_create)
                logger.info("GPS is live. Congrats! 🥳")

            else:
                logger.info(f"FollowUpGroups to be created: {len(groups_to_create)}.")
                logger.info(f"FollowUpGroupMemberships to be created: {len(memberships_to_create)}.")
