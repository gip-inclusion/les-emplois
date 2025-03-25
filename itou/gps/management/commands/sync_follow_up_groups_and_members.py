import datetime
from collections import defaultdict
from itertools import batched
from math import ceil

from django.conf import settings
from django.contrib.postgres.expressions import ArraySubquery
from django.db import transaction
from django.db.models import OuterRef
from django.db.models.functions import JSONObject

from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.eligibility.models.iae import EligibilityDiagnosis
from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.job_applications.models import JobApplication, JobApplicationState, JobApplicationTransitionLog
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.command import BaseCommand


CHUNK_SIZE = 1000


def get_users_contacts(ids):
    beneficiaries_qs = (
        User.objects.filter(pk__in=ids)
        .annotate(
            job_apps_senders=ArraySubquery(
                # only look for employer or prescriber
                JobApplication.objects.filter(job_seeker=OuterRef("pk"))
                .filter(sender__kind__in=[UserKind.EMPLOYER, UserKind.PRESCRIBER])
                .values(json=JSONObject(user_id="sender_id", timestamp="created_at"))
            )
        )
        .annotate(
            geiq_diagnosis_authors=ArraySubquery(
                GEIQEligibilityDiagnosis.objects.filter(job_seeker=OuterRef("pk")).values(
                    json=JSONObject(user_id="author_id", timestamp="created_at")
                )
            )
        )
        .annotate(
            iae_diagnosis_authors=ArraySubquery(
                EligibilityDiagnosis.objects.filter(job_seeker=OuterRef("pk")).values(
                    json=JSONObject(user_id="author_id", timestamp="created_at")
                )
            )
        )
        .annotate(
            job_app_accepted_by=ArraySubquery(
                JobApplicationTransitionLog.objects.filter(
                    job_application__job_seeker=OuterRef("pk"), to_state=JobApplicationState.ACCEPTED
                )
                .exclude(user=None)
                .values(json=JSONObject(user_id="user_id", timestamp="timestamp"))
            )
        )
    )

    users_contacts = {}
    for beneficiary in beneficiaries_qs:
        contacts = defaultdict(list)
        for user_id, timestamp in [
            (a["user_id"], datetime.datetime.fromisoformat(a["timestamp"]))
            for a in (
                beneficiary.job_apps_senders
                + beneficiary.geiq_diagnosis_authors
                + beneficiary.iae_diagnosis_authors
                + beneficiary.job_app_accepted_by
            )
        ]:
            contacts[user_id].append(timestamp)
        if beneficiary.created_by_id:
            contacts[beneficiary.created_by_id].append(beneficiary.date_joined)
        users_contacts[beneficiary.pk] = contacts
    return users_contacts


class Command(BaseCommand):
    help = "Create follow up groups and add beneficiaries."

    def add_arguments(self, parser):
        parser.add_argument(
            "--wet-run",
            dest="wet_run",
            action="store_true",
            help="Effectively create the memberships and groups in the database",
        )

    def handle(self, wet_run=False, **options):
        objects_created_by = User.objects.get(email=settings.GPS_GROUPS_CREATED_BY_EMAIL)
        self.logger.info(f"Script starting! 🚀 Memberships will be created by {objects_created_by}.")

        # Identify work to do for efficient batching.
        beneficiaries_pks = User.objects.filter(kind=UserKind.JOB_SEEKER).order_by("pk").values_list("pk", flat=True)

        self.logger.info(f"{len(beneficiaries_pks)} FollowUpGroups to update")
        chunks_total = ceil(len(beneficiaries_pks) / CHUNK_SIZE)

        chunks_count = 0
        for beneficiaries_ids in batched(beneficiaries_pks, CHUNK_SIZE):
            users_contacts = get_users_contacts(beneficiaries_ids)
            with transaction.atomic():
                groups = {
                    group.beneficiary_id: group
                    for group in FollowUpGroup.objects.filter(beneficiary_id__in=beneficiaries_ids)
                    .prefetch_related("memberships")
                    .select_for_update()
                }

                memberships_to_create = []
                memberships_to_update = []
                groups_to_create = []

                for beneficiary_id, contacts in users_contacts.items():
                    if group := groups.get(beneficiary_id):
                        # update or create memberships
                        memberships = {membership.member_id: membership for membership in group.memberships.all()}
                        for participant_id, timestamps in contacts.items():
                            if membership := memberships.get(participant_id):
                                last_contact_at = contacts[membership.member_id][-1]
                                if last_contact_at > membership.last_contact_at:
                                    membership.last_contact_at = last_contact_at
                                    memberships_to_update.append(membership)
                            else:
                                memberships_to_create.append(
                                    FollowUpGroupMembership(
                                        is_referent=False,
                                        member_id=participant_id,
                                        creator_id=objects_created_by.id,
                                        follow_up_group=group,
                                        created_in_bulk=True,
                                        created_at=timestamps[0],
                                        started_at=timestamps[0].date(),
                                        last_contact_at=timestamps[-1],
                                    )
                                )
                    elif contacts:
                        # create new group
                        # check all timestamps
                        group = FollowUpGroup(beneficiary_id=beneficiary_id, created_in_bulk=True)
                        groups_to_create.append(group)
                        for participant_id, timestamps in contacts.items():
                            memberships_to_create.append(
                                FollowUpGroupMembership(
                                    is_referent=False,
                                    member_id=participant_id,
                                    creator_id=objects_created_by.id,
                                    follow_up_group=group,
                                    created_in_bulk=True,
                                    created_at=timestamps[0],
                                    started_at=timestamps[0].date(),
                                    last_contact_at=timestamps[-1],
                                )
                            )

                if wet_run:
                    FollowUpGroupMembership.objects.bulk_update(
                        memberships_to_update, fields=["last_contact_at", "updated_at"]
                    )
                    FollowUpGroup.objects.bulk_create(groups_to_create)
                    FollowUpGroupMembership.objects.bulk_create(memberships_to_create)

                chunks_count += 1
                print(f"{chunks_count / chunks_total * 100:.2f}%", end="\r")
