import pathlib
import uuid
from itertools import batched
from math import ceil
from typing import NamedTuple

import numpy
import pandas
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.users.enums import UserKind
from itou.users.models import JobSeekerProfile, User
from itou.utils.admin import add_support_remark_to_obj
from itou.utils.command import BaseCommand


class AdvisorDetails(NamedTuple):
    first_name: str
    last_name: str
    code_safir_agence: str
    email: str


class JobSeekerDetails(NamedTuple):
    first_name: str
    last_name: str
    pole_emploi_id: str
    nir: str
    birthdate: str
    ft_gps_id: str


class Command(BaseCommand):
    """
    Import advisors from an Excel file (GPS)
    """

    help = "Import advisor contact information for existing job seeker profiles from GPS excel file."

    def add_arguments(self, parser):
        parser.add_argument(
            "import_csv_file",
            type=pathlib.Path,
            help="The filepath of the GPS export file, with extension .csv",
        )
        parser.add_argument(
            "--wet-run",
            dest="wet_run",
            action="store_true",
            help="Persist the changes to contacts in the database.",
        )

    def parse_gps_advisors_file(self, import_file):
        df = pandas.read_csv(
            import_file,
            converters={
                "code_agence": str,
                "identifiant_gps": int,
                "nir": str,
                "identifiant_local": str,
            },
            delimiter=";",
        )

        df.rename(
            columns={
                # exported data
                "identifiant_gps": "job_seeker_pk",
                "nom": "job_seeker_last_name",
                "prénom": "job_seeker_first_name",
                "identifiant_local": "job_seeker_pole_emploi_id",
                "date_de_naissance": "job_seeker_birthdate",
                "nir": "job_seeker_nir",
                # New data
                "nom_conseiller": "last_name",
                "prenom_conseiller": "first_name",
                "mail_conseiller": "email",
                "kn_individu_national": "job_seeker_ft_gps_id",
                "code_agence": "code_safir_agence",
            },
            inplace=True,
        )

        # Extract ft_gps_id:
        job_seeker_details = {}
        job_seekers_nb = df["job_seeker_pk"].nunique()
        for pk, last_name, first_name, pole_emploi_id, birthdate, nir, ft_gps_id in (
            df[
                [
                    "job_seeker_pk",
                    "job_seeker_last_name",
                    "job_seeker_first_name",
                    "job_seeker_pole_emploi_id",
                    "job_seeker_birthdate",
                    "job_seeker_nir",
                    "job_seeker_ft_gps_id",
                ]
            ]
            .fillna("")
            .drop_duplicates(subset=["job_seeker_pk"], keep=False)
            .itertuples(index=False)
        ):
            job_seeker_details[pk] = JobSeekerDetails(
                first_name=first_name,
                last_name=last_name,
                pole_emploi_id=pole_emploi_id,
                nir=nir,
                birthdate=birthdate,
                ft_gps_id=ft_gps_id,
            )
        self.logger.info(
            "Some job seekers were found multiple times, their ft_gps_id won't be saved: "
            f"{job_seekers_nb - len(job_seeker_details)} jobseekers"
        )

        # extract advisors
        df = df.replace("", numpy.nan).dropna(subset=["code_safir_agence", "last_name", "first_name", "email"])
        df = df[["job_seeker_pk", "code_safir_agence", "last_name", "first_name", "email"]]

        self.logger.info(f"Found {len(df)} rows from GPS export.")

        job_seekers_pks = list(
            User.objects.filter(pk__in=df["job_seeker_pk"], kind=UserKind.JOB_SEEKER).values_list("pk", flat=True)
        )
        non_prescriber_account_emails = list(
            User.objects.filter(email__in=df["email"])
            .exclude(kind=UserKind.PRESCRIBER)
            .values_list("email", flat=True)
        )
        pk_to_contact = {}
        invalid_pks = []
        for row in df.itertuples():
            if row.job_seeker_pk not in job_seekers_pks:
                invalid_pks.append(row.job_seeker_pk)
                continue
            if row.email in non_prescriber_account_emails:
                continue
            pk_to_contact[row.job_seeker_pk] = AdvisorDetails(
                first_name=row.first_name,
                last_name=row.last_name,
                code_safir_agence=row.code_safir_agence,
                email=row.email,
            )

        if invalid_pks:
            self.logger.warning(f"Some job seekers ids where not found: {invalid_pks}.")
        if non_prescriber_account_emails:
            self.logger.warning(
                f"Some advisor email are attached to non prescriber accounts: {non_prescriber_account_emails}."
            )

        return job_seeker_details, pk_to_contact

    def update_ft_gps_id(self, job_seeker_details, wet_run):
        jobseeker_profiles = list(
            JobSeekerProfile.objects.filter(pk__in=job_seeker_details, ft_gps_id=None).select_related("user")
        )
        profiles_to_update = []
        for jobseeker_profile in jobseeker_profiles:
            details = job_seeker_details[jobseeker_profile.pk]
            if all(
                [
                    jobseeker_profile.user.first_name == details.first_name,
                    jobseeker_profile.user.last_name == details.last_name,
                    jobseeker_profile.nir == details.nir,
                    jobseeker_profile.pole_emploi_id == details.pole_emploi_id,
                    str(jobseeker_profile.birthdate or "") == details.birthdate,
                ]
            ):
                jobseeker_profile.ft_gps_id = job_seeker_details[jobseeker_profile.pk].ft_gps_id
                profiles_to_update.append(jobseeker_profile)
        if wet_run:
            for batch in batched(profiles_to_update, 1000):
                JobSeekerProfile.objects.bulk_update(batch, fields=["ft_gps_id"])
        self.logger.info(f"Updated {len(profiles_to_update)} ft_gps_id values the database")

    def process_advisors(self, beneficiaries_id_to_contact, wet_run):
        objects_created_by = User.objects.get(email=settings.GPS_GROUPS_CREATED_BY_EMAIL)

        # Process advisors
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
                    .select_for_update(of=("self",), no_key=True)
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

    def handle(self, import_csv_file, wet_run=False, **options):
        job_seeker_details, beneficiaries_id_to_contact = self.parse_gps_advisors_file(import_csv_file)
        self.update_ft_gps_id(job_seeker_details, wet_run)
        self.process_advisors(beneficiaries_id_to_contact, wet_run)

        if not wet_run:
            self.logger.warning(
                "This was a dry run, nothing was committed. Execute the command with --wet-run to change this."
            )
