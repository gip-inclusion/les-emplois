import csv
import datetime
import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Case, F, Value, When
from django.urls import reverse

from itou.job_applications.models import JobApplication
from itou.users.models import User


class Command(BaseCommand):
    """
    Deduplicate job seekers.

    How are duplicates created?
    The identification of a person was done on the basis of the `email` field.
    But it happens that a SIAE (or a prescriber):
    - makes a typing error in the email
    - creates an email on the fly because job seekers do not remember their own
    - enters a fancy email
    - enters another family member's email
    This results in duplicates that we try to correct when possible whith this
    management command.

    The NIR is now used to ensure the uniqueness of job seekers and should be
    the safety pin that prevents duplicates.

    This command is temporary and should be deleted as soon as a sufficient
    number of users have a NIR.

    To run the command without any change in DB and have a preview of which
    accounts will be merged:
        django-admin deduplicate_job_seekers --dry-run --no-csv

    To merge duplicates job seekers in the database:
        django-admin deduplicate_job_seekers
    """

    help = "Deduplicate job seekers."

    EASY_CASES_LOGS = []
    HARD_CASES_LOGS = []

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Only display data to deduplicate")
        parser.add_argument("--no-csv", dest="no_csv", action="store_true", help="Do not export results in CSV")

    def set_logger(self, verbosity):
        """
        Set logger level based on the verbosity option.
        """
        handler = logging.StreamHandler(self.stdout)

        self.logger = logging.getLogger(__name__)
        self.logger.propagate = False
        self.logger.addHandler(handler)

        self.logger.setLevel(logging.INFO)
        if verbosity >= 1:
            self.logger.setLevel(logging.DEBUG)

    def merge_easy_cases(self, duplicates, target, nirs):
        """
        Merge easy cases: when None or 1 PASS IAE was issued accross multiple accounts.
        """

        assert target.email

        users_to_delete = [u for u in duplicates if u != target]

        target_admin_path = reverse("admin:users_user_change", args=[target.pk])
        target_admin_url = f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}{target_admin_path}"
        self.EASY_CASES_LOGS.append(
            {
                "Compte de destination": target.email,
                "URL admin du compte de destination": target_admin_url,
                "Nombre de doublons": len(users_to_delete),
                "Doublons fusionnés": " ; ".join([u.email for u in users_to_delete]),
            }
        )

        # Debug info.
        self.logger.debug(f"[easy] {self.EASY_CASES_LOGS[-1].values()}")

        for user in users_to_delete:

            assert user.approvals.count() == 0

            if not self.dry_run:
                user.job_applications.update(
                    job_seeker=target,
                    sender=Case(
                        When(sender_kind=JobApplication.SENDER_KIND_JOB_SEEKER, then=Value(target.pk)),
                        default=F("sender"),
                        output_field=JobApplication._meta.get_field("sender"),
                    ),
                )
                user.eligibility_diagnoses.update(job_seeker=target)
                user.delete()

        # If only one NIR exists for all the duplicates, it is reassigned to
        # the target account. This must be executed at the end because of the
        # uniqueness constraint.
        if len(nirs) == 1 and not target.nir:
            target.nir = nirs[0]
            if not self.dry_run:
                target.save()

    def handle_hard_cases(self, duplicates, num):
        """
        Only log hard cases.
        """

        for duplicate in duplicates:
            log_info = {
                "Numéro": num,
                "Nombre de doublons": len(duplicates),
                "Email": duplicate.email,
                "Numéro PASS IAE": "",
                "Début PASS IAE": "",
                "Fin PASS IAE": "",
                "Lien admin PASS IAE": "",
            }

            approval = duplicate.approvals.last()
            if approval:
                approval_admin_path = reverse("admin:approvals_approval_change", args=[approval.pk])
                approval_admin_url = f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}{approval_admin_path}"
                log_info["Numéro PASS IAE"] = approval.number
                log_info["Début PASS IAE"] = approval.start_at.strftime("%d/%m/%Y")
                log_info["Fin PASS IAE"] = approval.end_at.strftime("%d/%m/%Y")
                log_info["Lien admin PASS IAE"] = approval_admin_url

            # Debug info.
            self.logger.debug(f"[hard] {log_info.values()}")

            self.HARD_CASES_LOGS.append(log_info)

    def handle(self, dry_run=False, no_csv=False, **options):

        self.set_logger(options.get("verbosity"))

        self.dry_run = dry_run
        self.no_csv = no_csv

        self.logger.debug("Starting. Good luck…")

        count_easy_cases = 0
        count_hard_cases = 0

        duplicates_dict = User.objects.get_duplicates_by_pole_emploi_id(
            prefetch_related_lookups=["approvals", "eligibility_diagnoses"]
        )

        for pe_id, duplicates in duplicates_dict.items():

            users_with_approval = [u for u in duplicates if u.approvals.exists()]

            # Ensure all users have the same birthdate.
            assert all(user.birthdate == duplicates[0].birthdate for user in duplicates)

            # Easy cases.
            # None or 1 PASS IAE was issued for the same person with multiple accounts.
            if len(users_with_approval) <= 1:

                nirs = [u.nir for u in duplicates if u.nir]

                if len(nirs) > 1:
                    # Finally there may still be duplicates, even with the NIR.
                    # We do nothing with them for the moment because it is
                    # impossible to identify which NIR is the right one.
                    continue

                count_easy_cases += 1
                target = None

                # Give priority to the user with a PASS IAE.
                user_with_approval = next((u for u in duplicates if u.approvals.exists()), None)
                if user_with_approval:
                    target = user_with_approval

                # Handle duplicates without any PASS IAE.
                else:
                    # Give priority to the first user who already logged in…
                    first_autonomous_user = next((u for u in duplicates if u.last_login), None)
                    if first_autonomous_user:
                        target = first_autonomous_user
                    # …or choose an arbitrary user to merge others into.
                    else:
                        target = duplicates[0]

                self.merge_easy_cases(duplicates, target=target, nirs=nirs)

            # Hard cases.
            # More than one PASS IAE was issued for the same person.
            # We only handle logs for the moment, we don't know yet how to merge them.
            elif len(users_with_approval) > 1:
                count_hard_cases += 1
                self.handle_hard_cases(duplicates, count_hard_cases)

        if not self.no_csv:
            self.to_csv(
                "easy-duplicates",
                [
                    "Compte de destination",
                    "URL admin du compte de destination",
                    "Nombre de doublons",
                    "Doublons fusionnés",
                ],
                self.EASY_CASES_LOGS,
            )
            self.to_csv(
                "hard-duplicates",
                [
                    "Numéro",  # Lines with the same number are duplicates.
                    "Nombre de doublons",
                    "Email",
                    "Numéro PASS IAE",
                    "Début PASS IAE",
                    "Fin PASS IAE",
                    "Lien admin PASS IAE",
                ],
                self.HARD_CASES_LOGS,
            )

        self.logger.debug("-" * 80)
        self.logger.debug(f"{count_easy_cases} easy cases merged.")
        self.logger.debug(f"{count_hard_cases} hard cases found.")

        self.logger.debug("-" * 80)
        self.logger.debug("Done.")

    def to_csv(self, filename, fieldnames, data):
        log_datetime = datetime.datetime.now().strftime("%d-%m-%Y-%H-%M-%S")
        path = f"{settings.EXPORT_DIR}/{log_datetime}-{filename}-{settings.ITOU_ENVIRONMENT.lower()}.csv"
        with open(path, "w") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            writer.writerows(data)
