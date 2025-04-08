import pathlib
import uuid
from itertools import batched
from math import ceil
from typing import NamedTuple

import pandas
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.admin import add_support_remark_to_obj
from itou.utils.command import BaseCommand


class AdvisorDetails(NamedTuple):
    first_name: str
    last_name: str
    code_safir_agence: str
    email: str


class Command(BaseCommand):
    """
    Import advisors from an Excel file (GPS)
    """

    help = "Import advisor contact information for existing job seeker profiles from GPS excel file."

    def add_arguments(self, parser):
        parser.add_argument(
            "import_excel_file",
            type=pathlib.Path,
            help="The filepath of the GPS export file, with extension .xlsx",
        )
        parser.add_argument(
            "--wet-run",
            dest="wet_run",
            action="store_true",
            help="Persist the changes to contacts in the database.",
        )

    def parse_gps_advisors_file(self, import_file):
        df = pandas.read_excel(
            import_file,
            converters={
                "code_safir_agence": str,
                "ID": int,
            },
        )
        df = df.dropna(
            subset=["prenom_cdde", "nom_cdde", "code_safir_agence", "mail_cdde"]
        )  # only keep lines with all user information
        df = df[["ID", "prenom_cdde", "nom_cdde", "code_safir_agence", "mail_cdde"]]

        self.logger.info(f"Found {len(df)} rows from GPS export.")

        job_seekers_pks = list(
            User.objects.filter(pk__in=df["ID"], kind=UserKind.JOB_SEEKER).values_list("pk", flat=True)
        )
        non_prescriber_account_emails = list(
            User.objects.filter(email__in=df["mail_cdde"])
            .exclude(kind=UserKind.PRESCRIBER)
            .values_list("email", flat=True)
        )
        pk_to_contact = {}
        invalid_pks = []
        for row in df.itertuples():
            if row.ID not in job_seekers_pks:
                invalid_pks.append(row.ID)
                continue
            if row.mail_cdde in non_prescriber_account_emails:
                continue
            pk_to_contact[row.ID] = AdvisorDetails(
                first_name=row.prenom_cdde,
                last_name=row.nom_cdde,
                code_safir_agence=row.code_safir_agence,
                email=row.mail_cdde,
            )

        if invalid_pks:
            self.logger.warning(f"Some job seekers ids where not found: {invalid_pks}.")
        if non_prescriber_account_emails:
            self.logger.warning(
                f"Some advisor email are attached to non prescriber accounts: {non_prescriber_account_emails}."
            )

        return pk_to_contact

    def handle(self, import_excel_file, wet_run=False, **options):
        objects_created_by = User.objects.get(email=settings.GPS_GROUPS_CREATED_BY_EMAIL)

        # parse the excel import
        beneficiaries_id_to_contact = self.parse_gps_advisors_file(import_excel_file)

        self.logger.info(f"Matched {len(beneficiaries_id_to_contact)} users in the database")

        chunk_size = 1000
        chunks_total = ceil(len(beneficiaries_id_to_contact) / chunk_size)
        created_prescriber_count = 0

        if wet_run:
            FollowUpGroupMembership.objects.filter(is_referent_certified=True).exclude(
                follow_up_group__beneficiary_id__in=beneficiaries_id_to_contact
            ).update(is_referent_certified=False)

        for chunk_idx, batch in enumerate(batched(beneficiaries_id_to_contact.items(), chunk_size), 1):
            batch = dict(batch)
            with transaction.atomic():
                if wet_run:
                    FollowUpGroupMembership.objects.filter(is_referent_certified=True).filter(
                        follow_up_group__beneficiary_id__in=batch.keys()
                    ).update(is_referent_certified=False)
                prescribers_to_create = []
                groups_to_create = []
                follow_up_memberships_to_create = []
                follow_up_memberships_to_update = []
                prescriber_memberships_to_create = []

                groups = {
                    group.beneficiary_id: group
                    for group in FollowUpGroup.objects.filter(beneficiary_id__in=batch.keys())
                    .prefetch_related("memberships")
                    .select_for_update()
                }

                prescribers_dict = {
                    user.email.lower(): user
                    for user in User.objects.filter(
                        kind=UserKind.PRESCRIBER,
                        email__in=[o.email for o in batch.values()],
                    )
                }
                for beneficiary_id, advisor_details in batch.items():
                    prescriber = prescribers_dict.get(advisor_details.email.lower())
                    if prescriber is None:
                        prescriber = User(
                            username=uuid.uuid4(),
                            email=advisor_details.email.lower(),
                            first_name=advisor_details.first_name,
                            last_name=advisor_details.last_name,
                            kind=UserKind.PRESCRIBER,
                        )
                        if advisor_details.code_safir_agence:
                            if organization := PrescriberOrganization.objects.filter(
                                code_safir_pole_emploi=advisor_details.code_safir_agence
                            ).first():
                                prescriber_memberships_to_create.append(
                                    PrescriberMembership(user=prescriber, organization=organization)
                                )
                        prescribers_dict[prescriber.email] = prescriber
                        prescribers_to_create.append(prescriber)

                    group = groups.get(beneficiary_id)
                    if group is None:
                        group = FollowUpGroup(beneficiary_id=beneficiary_id, created_in_bulk=True)
                        groups_to_create.append(group)

                    membership = None
                    if prescriber.pk and group.pk:
                        memberships = {m.member_id: m for m in group.memberships.all()}
                        membership = memberships.get(prescriber.pk)
                    if membership is None:
                        follow_up_memberships_to_create.append(
                            FollowUpGroupMembership(
                                is_referent_certified=True,
                                member=prescriber,
                                creator_id=objects_created_by.id,
                                follow_up_group=group,
                                created_in_bulk=True,
                                created_at=timezone.now(),
                                started_at=timezone.localdate(),
                                last_contact_at=timezone.now(),
                            )
                        )
                    else:
                        membership.is_referent_certified = True
                        membership.ended_at = None
                        membership.end_reason = None
                        membership.last_contact_at = timezone.now()
                        membership.is_active = True
                        follow_up_memberships_to_update.append(membership)

                if wet_run:
                    User.objects.bulk_create(prescribers_to_create)
                    FollowUpGroup.objects.bulk_create(groups_to_create)
                    FollowUpGroupMembership.objects.bulk_update(
                        follow_up_memberships_to_update,
                        fields=[
                            "is_referent_certified",
                            "updated_at",
                            "ended_at",
                            "end_reason",
                            "last_contact_at",
                            "is_active",
                        ],
                    )
                    FollowUpGroupMembership.objects.bulk_create(follow_up_memberships_to_create)
                    PrescriberMembership.objects.bulk_create(prescriber_memberships_to_create)
                    for prescriber in prescribers_to_create:
                        add_support_remark_to_obj(prescriber, "Créé par l'import des référents FT pour GPS")

            created_prescriber_count += len(prescribers_to_create)

            self.logger.info(f"{chunk_idx / chunks_total * 100:.2f}%")

        self.logger.info("-" * 80)
        self.logger.info(
            f"Import complete. {created_prescriber_count} prescribers were created "
            f"and {len(beneficiaries_id_to_contact)} certified referent were set."
        )
        if not wet_run:
            self.logger.warning(
                "This was a dry run, nothing was committed. Execute the command with --wet-run to change this."
            )
