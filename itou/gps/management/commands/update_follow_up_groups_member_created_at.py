import datetime
import logging
from math import ceil

from django.conf import settings
from django.contrib.postgres.expressions import ArraySubquery
from django.db import transaction
from django.db.models import OuterRef, Q
from django.db.models.functions import JSONObject
from django.utils import timezone

from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.eligibility.models.iae import EligibilityDiagnosis
from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.job_applications.models import JobApplication, JobApplicationState, JobApplicationTransitionLog
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

    def _bulk_created_lookup(self):
        # all created in bulk groups with a datetime AFTER GPS_GROUPS_CREATED_AT_DATE
        # so that already updated groups are ignored
        created_at_as_dt = datetime.datetime.combine(
            settings.GPS_GROUPS_CREATED_AT_DATE, datetime.time(0, 0, 0), tzinfo=datetime.UTC
        )
        return Q(created_at__gte=created_at_as_dt, created_in_bulk=True)

    def handle(self, wet_run=False, **options):
        beneficiaries_pks = (
            FollowUpGroup.objects.filter(self._bulk_created_lookup())
            .values_list("beneficiary_id", flat=True)
            .order_by("pk")
            .distinct()
        )
        logger.info(f"{len(beneficiaries_pks)} FollowUpGroups to update")
        chunks_total = ceil(len(beneficiaries_pks) / 1000)

        chunks_count = 0
        for beneficiaries_ids in chunks(beneficiaries_pks, 1000):
            beneficiaries_qs = (
                User.objects.filter(pk__in=beneficiaries_ids)
                .annotate(
                    job_apps_senders=ArraySubquery(
                        JobApplication.objects.filter(job_seeker=OuterRef("pk"))
                        .exclude(sender=None)
                        .exclude(state=JobApplicationState.NEW)
                        .values(json=JSONObject(user_id="sender_id", timestamp="created_at"))
                    )
                )
                .annotate(
                    geiq_diagnosis=ArraySubquery(
                        GEIQEligibilityDiagnosis.objects.filter(job_seeker=OuterRef("pk")).values(
                            json=JSONObject(user_id="author_id", timestamp="created_at")
                        )
                    )
                )
                .annotate(
                    iae_diagnosis=ArraySubquery(
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

            groups = (
                FollowUpGroup.objects.filter(beneficiary_id__in=beneficiaries_ids)
                .prefetch_related("memberships")
                .select_for_update()
            )

            users_first_contacts = {}
            for beneficiary in beneficiaries_qs:
                first_contacts = {}
                for user_id, timestamp in sorted(
                    (a["user_id"], a["timestamp"])
                    for a in (
                        beneficiary.job_apps_senders
                        + beneficiary.geiq_diagnosis
                        + beneficiary.iae_diagnosis
                        + beneficiary.job_app_accepted_by
                    )
                ):
                    first_contacts.setdefault(user_id, timestamp)
                users_first_contacts[beneficiary.pk] = first_contacts

            with transaction.atomic():
                memberships = []
                for group in groups:
                    if not users_first_contacts[group.beneficiary_id]:
                        # something changed in the database, don't do anything
                        continue
                    group.created_at = datetime.datetime.fromisoformat(
                        min(users_first_contacts[group.beneficiary_id].values())
                    )
                    group.updated_at = timezone.now()
                    for membership in group.memberships.all():
                        if membership.created_in_bulk:
                            if timestamp := users_first_contacts[group.beneficiary_id].get(membership.member_id):
                                membership.created_at = datetime.datetime.fromisoformat(
                                    users_first_contacts[group.beneficiary_id][membership.member_id]
                                )
                                membership.updated_at = timezone.now()
                                memberships.append(membership)
                            else:
                                # something changed in the database, don't do anything
                                pass

                if wet_run:
                    FollowUpGroup.objects.bulk_update(groups, fields=["created_at", "updated_at"])
                    FollowUpGroupMembership.objects.bulk_update(memberships, fields=["created_at", "updated_at"])
                chunks_count += 1
                print(f"{chunks_count/chunks_total*100:.2f}%", end="\r")
