import time
from collections import defaultdict
from datetime import datetime
from itertools import batched
from math import ceil

from django.contrib.postgres.expressions import ArraySubquery
from django.db import transaction
from django.db.models import OuterRef, Value
from django.db.models.functions import JSONObject

from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.eligibility.models.iae import EligibilityDiagnosis
from itou.job_applications.models import JobApplication
from itou.users.enums import ActionKind, UserKind
from itou.users.models import JobSeekerAssignment, User
from itou.utils.command import BaseCommand


CHUNK_SIZE = 1000


def get_users_contacts(ids):
    job_seekers_qs = (
        User.objects.filter(pk__in=ids)
        .select_related("created_by", "jobseeker_profile__created_by_prescriber_organization")
        .annotate(
            job_apps_senders=ArraySubquery(
                JobApplication.objects.filter(job_seeker=OuterRef("pk"))
                # not using sender_kind as discrepancies exist
                .filter(sender__kind=UserKind.PRESCRIBER)
                .values(
                    json=JSONObject(
                        user_id="sender_id",
                        prescriber_organization_id="sender_prescriber_organization_id",
                        timestamp="created_at",
                        action_kind=Value(ActionKind.APPLY),
                    )
                )
            )
        )
        .annotate(
            geiq_diagnosis_authors=ArraySubquery(
                GEIQEligibilityDiagnosis.objects.filter(job_seeker=OuterRef("pk"))
                # not using author_kind as discrepancies exist
                .filter(author__kind=UserKind.PRESCRIBER)
                .values(
                    json=JSONObject(
                        user_id="author_id",
                        prescriber_organization_id="author_prescriber_organization_id",
                        timestamp="created_at",
                        action_kind=Value(ActionKind.GEIQ_ELIGIBILITY),
                    )
                )
            )
        )
        .annotate(
            iae_diagnosis_authors=ArraySubquery(
                EligibilityDiagnosis.objects.filter(job_seeker=OuterRef("pk"))
                # not using author_kind as discrepancies exist
                .filter(author__kind=UserKind.PRESCRIBER)
                .values(
                    json=JSONObject(
                        user_id="author_id",
                        prescriber_organization_id="author_prescriber_organization_id",
                        timestamp="created_at",
                        action_kind=Value(ActionKind.IAE_ELIGIBILITY),
                    )
                )
            )
        )
    )

    users_contacts = {}
    for job_seeker in job_seekers_qs:
        contacts = defaultdict(list)
        for user_id, prescriber_organization_id, timestamp, action_kind in [
            (
                a["user_id"],
                a["prescriber_organization_id"],
                datetime.fromisoformat(a["timestamp"]),
                a["action_kind"],
            )
            for a in (
                job_seeker.job_apps_senders + job_seeker.geiq_diagnosis_authors + job_seeker.iae_diagnosis_authors
            )
        ]:
            contacts[(user_id, prescriber_organization_id)].append(
                {"timestamp": timestamp, "action_kind": action_kind}
            )
        if job_seeker.created_by and job_seeker.created_by.kind == UserKind.PRESCRIBER:
            contacts[
                (
                    job_seeker.created_by_id,
                    # created_by_prescriber_organization was only introduced in Feb 2025
                    job_seeker.jobseeker_profile.created_by_prescriber_organization_id,
                )
            ].append({"timestamp": job_seeker.date_joined, "action_kind": ActionKind.CREATE.value})
        users_contacts[job_seeker.pk] = contacts

    return users_contacts


class Command(BaseCommand):
    help = "Create objects that link prescribers to assigned job seekers."

    def add_arguments(self, parser):
        parser.add_argument(
            "--wet-run",
            dest="wet_run",
            action="store_true",
            help="Effectively create the assignments in the database.",
        )

    def handle(self, wet_run=False, **options):
        start_time = time.perf_counter()
        self.logger.info("Script starting!")

        # Identify work to do for efficient batching.
        job_seekers_pks = User.objects.filter(kind=UserKind.JOB_SEEKER).order_by("pk").values_list("pk", flat=True)

        self.logger.info(f"{len(job_seekers_pks)} JobSeeker to assign.")
        chunks_total = ceil(len(job_seekers_pks) / CHUNK_SIZE)
        count_created, count_updated = 0, 0

        chunks_count = 0
        for chunks_count, job_seekers_ids in enumerate(batched(job_seekers_pks, CHUNK_SIZE)):
            users_contacts = get_users_contacts(job_seekers_ids)

            with transaction.atomic():
                assignments = {
                    (
                        assignment.job_seeker_id,
                        assignment.prescriber_id,
                        assignment.prescriber_organization_id,
                    ): assignment
                    for assignment in JobSeekerAssignment.objects.filter(
                        job_seeker_id__in=job_seekers_ids
                    ).select_for_update(of=("self",), no_key=True)
                }

                assignments_to_create = []
                assignments_to_update = set()

                for job_seeker_id, contacts in users_contacts.items():
                    for (prescriber_id, prescriber_organization_id), actions in contacts.items():
                        sorted_actions = sorted(actions, key=lambda a: a.get("timestamp"))
                        first_action = sorted_actions[0]
                        last_action = sorted_actions[-1]

                        if assignment := assignments.get((job_seeker_id, prescriber_id, prescriber_organization_id)):
                            # update assignment
                            if last_action["timestamp"] > assignment.updated_at:
                                assignment.updated_at = last_action["timestamp"]
                                assignment.last_action_kind = last_action["action_kind"]
                                assignments_to_update.add(assignment)
                            if first_action["timestamp"] < assignment.created_at:
                                assignment.created_at = first_action["timestamp"]
                                assignments_to_update.add(assignment)

                        else:
                            # create new assignment
                            assignments_to_create.append(
                                JobSeekerAssignment(
                                    job_seeker_id=job_seeker_id,
                                    prescriber_id=prescriber_id,
                                    prescriber_organization_id=prescriber_organization_id,
                                    created_at=first_action["timestamp"],
                                    updated_at=last_action["timestamp"],
                                    last_action_kind=last_action["action_kind"],
                                )
                            )

                count_updated += len(assignments_to_update)
                count_created += len(assignments_to_create)
                if wet_run:
                    JobSeekerAssignment.objects.bulk_update(
                        assignments_to_update, fields=["last_action_kind", "created_at", "updated_at"]
                    )
                    JobSeekerAssignment.objects.bulk_create(assignments_to_create)

                print(
                    f"{chunks_count / chunks_total * 100:.2f}% - "
                    f"elapsed time: {time.perf_counter() - start_time:.2f}s",
                    end="\r",
                )
        print(f"Created {count_created} assignments, updated {count_updated} assignments")
