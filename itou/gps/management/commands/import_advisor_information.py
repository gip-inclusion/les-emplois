import logging
from math import ceil

from django.db import transaction

from itou.gps.models import FranceTravailContact
from itou.gps.utils import create_or_update_advisor, parse_gps_advisors_file
from itou.users.enums import UserKind
from itou.users.models import JobSeekerProfile, User
from itou.utils.command import BaseCommand
from itou.utils.iterators import chunks


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Import advisors from an Excel file (GPS)
    """

    help = "Import advisor contact information for existing job seeker profiles from GPS excel file."

    def add_arguments(self, parser):
        parser.add_argument(
            "import_excel_file",
            type=str,
            help="The file directory of the GPS export file, with extension .xlsx",
        )
        parser.add_argument(
            "--wet-run",
            dest="wet_run",
            action="store_true",
            help="Persist the changes to contacts in the database.",
        )

    def handle(self, import_excel_file, wet_run=False, **options):
        # parse the excel import
        nir_to_contact = parse_gps_advisors_file(import_excel_file)

        beneficiaries_pks = User.objects.filter(
            kind=UserKind.JOB_SEEKER, jobseeker_profile__nir__in=nir_to_contact
        ).values_list("pk", flat=True)
        logger.info(f"Matched {len(beneficiaries_pks)} users in the database")

        chunk_size = 1000
        chunks_total = ceil(len(beneficiaries_pks) / chunk_size)
        created_rows_count = 0
        updated_rows_count = 0

        for chunk_idx, chunked_beneficiary_pks in enumerate(chunks(beneficiaries_pks, chunk_size), 1):
            # NOTE: cannot use select_for_update below
            # NotSupportedError: FOR UPDATE cannot be applied to the nullable side of an outer join
            implicated_profiles = JobSeekerProfile.objects.filter(user_id__in=chunked_beneficiary_pks).select_related(
                "advisor_information"
            )

            with transaction.atomic():
                contacts_to_create = []
                contacts_to_update = []

                for profile in implicated_profiles:
                    advisor, created = create_or_update_advisor(profile, nir_to_contact, commit=False)
                    if created:
                        contacts_to_create.append(advisor)
                    else:
                        contacts_to_update.append(advisor)

                if wet_run:
                    FranceTravailContact.objects.bulk_create(contacts_to_create)
                    FranceTravailContact.objects.bulk_update(contacts_to_update, fields=["name", "email"])

            created_rows_count += len(contacts_to_create)
            updated_rows_count += len(contacts_to_update)

            logger.info(f"{chunk_idx/chunks_total*100:.2f}%")

        logger.info("-" * 80)
        logger.info(
            f"Import complete. {created_rows_count} contact details were created "
            f"and {updated_rows_count} were updated."
        )
        missing_contact_details = JobSeekerProfile.objects.filter(advisor_information__isnull=True).count()
        if missing_contact_details > 0:
            logger.info(f"{missing_contact_details} profiles are still missing contact details.")
        if not wet_run:
            logger.warning(
                "This was a dry run, nothing was committed. Execute the command with --wet-run to change this."
            )
