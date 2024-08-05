import logging
import os
from math import ceil

import pandas as pd
from django.conf import settings
from django.db import transaction
from django.db.models import Case, F, Q, When
from django.utils import timezone

from itou.gps.models import FollowUpGroupMembership
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.command import BaseCommand
from itou.utils.iterators import chunks
from itou.utils.python import timeit


logger = logging.getLogger(__name__)


@timeit
def get_df():
    # NOM	PRENOM	NIR	DATE DE NAISSANCE	ASSEDIC	DC_STRUCTUREPRINCIPALEDE	DC_AGENTREFERENT	DC_STRUCTURERATTACH	DC_NOMAGENTREFERENT	DC_MAIL	DC_LBLPOSITIONNEMENTIAE

    import_file = os.path.join(settings.IMPORT_DIR, "export_gps.xlsx")
    info_stats = {}

    df = pd.read_excel(
        import_file,
        converters={
            "NIR": str,
            "DC_MAIL": str,
        },
    )
    df = df.rename(columns={"NIR": "nir", "DC_MAIL": "prescriber_email"})
    return df


class Command(BaseCommand):
    """
    Update GPS is_referent info.
    """

    help = "Import job seeker's France Travail referents."

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    @timeit
    def handle(self, *, wet_run, **options):
        df = get_df()
        logger.info(f"Row in file: {len(df)}.")

        memberships_to_update_counter = 0
        memberships_not_updated_counter = 0

        beneficiaries_pks = (
            User.objects.filter(kind=UserKind.JOB_SEEKER, jobseeker_profile__nir__in=df["nir"].tolist())
            .exclude(follow_up_group__isnull=True)
            .values_list("pk", flat=True)
        )
        logger.info(f"{len(beneficiaries_pks)} job seekers found.")

        chunks_total = ceil(len(beneficiaries_pks) / 1000)

        chunks_count = 0
        for beneficiaries_ids in chunks(beneficiaries_pks, 1000):
            beneficiaries_qs = User.objects.filter(pk__in=beneficiaries_ids)
            is_france_travail = Case(When(Q(member__email__endswith="@francetravail.fr"), then=True))
            memberships = (
                FollowUpGroupMembership.objects.filter(follow_up_group__beneficiary_id__in=beneficiaries_qs)
                .filter(member__kind=UserKind.PRESCRIBER)
                .annotate(member_kind_prescriber_FT=is_france_travail)
                .annotate(job_seeker_nir=F("follow_up_group__beneficiary__jobseeker_profile__nir"))
                .annotate(member_email=F("member__email"))
            )

            # Unable to use select_for_update because of the annotations above.
            # django.db.utils.NotSupportedError: FOR UPDATE cannot be applied to the nullable side of an outer join
            memberships = memberships.filter(member_kind_prescriber_FT=True)
            logger.info(f"{memberships.count()} memberships found in this loop.")

            with transaction.atomic():
                memberships_to_update = []
                for membership in memberships.all():
                    df_result = df.loc[
                        (df["nir"] == membership.job_seeker_nir) & (df["prescriber_email"] == membership.member_email)
                    ]
                    if not df_result.empty:
                        membership.is_referent = True
                        membership.updated_at = timezone.now()
                        memberships_to_update.append(membership)
                        memberships_to_update_counter += 1
                    else:
                        # Create membership if FT member exists.
                        memberships_not_updated_counter += 1

                if wet_run:
                    FollowUpGroupMembership.objects.bulk_update(
                        memberships_to_update, fields=["is_referent", "updated_at"]
                    )
                chunks_count += 1
                logger.info(f"{chunks_count/chunks_total*100:.2f}%")

        # Display some "stats" about the dataset
        logger.info("-" * 80)
        logger.info(f"memberships_to_update: {memberships_to_update_counter}")
        logger.info(f"memberships_not_updated: {memberships_not_updated_counter}")
