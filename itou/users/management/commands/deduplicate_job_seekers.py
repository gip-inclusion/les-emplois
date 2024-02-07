import datetime

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db.models import Case, F, Value, When
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from tqdm import tqdm

from itou.job_applications.enums import SenderKind
from itou.job_applications.models import JobApplication
from itou.users.models import User
from itou.utils.command import BaseCommand
from itou.utils.management_commands import DeprecatedLoggerMixin, XlsxExportMixin
from itou.utils.urls import get_absolute_url


class Command(XlsxExportMixin, DeprecatedLoggerMixin, BaseCommand):
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
        django-admin deduplicate_job_seekers --wet-run --no-xlsx

    To merge duplicates job seekers in the database:
        django-admin deduplicate_job_seekers
    """

    help = "Deduplicate job seekers."

    EASY_DUPLICATES_LOGS = []
    HARD_DUPLICATES_LOGS = []
    NIR_DUPLICATES_LOGS = []

    EASY_DUPLICATES_COUNT = 0
    HARD_DUPLICATES_COUNT = 0
    NIR_DUPLICATES_COUNT = 0

    def add_arguments(self, parser):
        parser.add_argument(
            "--wet-run", dest="wet_run", action="store_true", help="Actually write information in the database"
        )
        parser.add_argument("--no-xlsx", dest="no_xlsx", action="store_true", help="Do not export results in XLSX")

    def handle_easy_duplicates(self, duplicates, target, nirs):
        """
        Easy duplicates: there is 0 or 1 PASS IAE in the duplicates group.

        We can merge duplicates.
        """
        assert target.email

        users_to_delete = [u for u in duplicates if u != target]

        target_admin_path = reverse("admin:users_user_change", args=[target.pk])
        target_admin_url = get_absolute_url(target_admin_path)
        log_info = [
            target.email,
            target_admin_url,
            len(users_to_delete),
            " ; ".join([u.email for u in users_to_delete]),
        ]
        self.EASY_DUPLICATES_LOGS.append(log_info)

        # Debug info (when verbosity >= 1).
        self.logger.debug(f"[easy] {log_info}")

        for user in users_to_delete:
            assert user.approvals.count() == 0

            if self.wet_run:
                user.job_applications.update(
                    job_seeker=target,
                    sender=Case(
                        When(sender_kind=SenderKind.JOB_SEEKER, then=Value(target.pk)),
                        default=F("sender"),
                        output_field=JobApplication._meta.get_field("sender"),
                    ),
                )
                user.eligibility_diagnoses.update(job_seeker=target)
                user.delete()

        # If only one NIR exists for all the duplicates, it is reassigned to
        # the target account. This must be executed at the end because of the
        # uniqueness constraint.
        if len(nirs) == 1 and not target.jobseeker_profile.nir:
            target.jobseeker_profile.nir = nirs[0]
            target.jobseeker_profile.lack_of_nir_reason = ""
            if self.wet_run:
                target.jobseeker_profile.save()

    def handle_hard_duplicates(self, duplicates):
        """
        Hard duplicates: there are several PASS IAE in the group of duplicates.

        These cases will not be merged because they may have already been used
        (ASP, FSE etc.).

        We will live with this technical debt until further notice.
        """
        job_applications_path = reverse("admin:job_applications_jobapplication_changelist")
        freshness_threshold = timezone.now() - relativedelta(months=3)
        for duplicate in duplicates:
            args = {"job_seeker_id": duplicate.id, "created_at__gte": freshness_threshold}
            recent_job_applications_url = f"{get_absolute_url(job_applications_path)}?{urlencode(args)}"
            approval = duplicate.approvals.last()
            if approval:
                approval_admin_path = reverse("admin:approvals_approval_change", args=[approval.pk])
                approval_admin_url = get_absolute_url(approval_admin_path)
            log_info = [
                self.HARD_DUPLICATES_COUNT,
                len(duplicates),
                duplicate.email,
                duplicate.jobseeker_profile.nir,
                duplicate.birthdate,
                approval.number if approval else "",
                approval.start_at.strftime("%d/%m/%Y") if approval else "",
                approval.end_at.strftime("%d/%m/%Y") if approval else "",
                approval_admin_url if approval else "",
                recent_job_applications_url,
            ]

            # Debug info (when verbosity >= 1).
            self.logger.debug(f"[hard] {log_info}")

            # We are only logging for now.
            self.HARD_DUPLICATES_LOGS.append(log_info)

    def handle_nir_duplicates(self, duplicates):
        """
        Duplicates with different NIR.

        There may still be duplicates, even with the NIR.
        We do nothing with them for the moment because it is impossible to
        identify which NIR is the right one.

        We can transfer this information to the support for manual correction.
        """
        for duplicate in duplicates:
            log_info = [
                self.NIR_DUPLICATES_COUNT,
                len(duplicates),
                duplicate.email,
                duplicate.nir,
            ]

            # Debug info (when verbosity >= 1).
            self.logger.debug(f"[NIR] {log_info}")

            # We are only logging for now.
            self.NIR_DUPLICATES_LOGS.append(log_info)

    def handle(self, *, wet_run, no_xlsx, **options):
        self.set_logger(options.get("verbosity"))

        self.wet_run = wet_run
        self.no_xlsx = no_xlsx

        self.stdout.write("Starting. Good luck…")

        duplicates_dict = User.objects.get_duplicates_by_pole_emploi_id(
            prefetch_related_lookups=["approvals", "eligibility_diagnoses"]
        )

        pbar = tqdm(total=len(duplicates_dict.items()))

        for pe_id, duplicates in duplicates_dict.items():
            pbar.update(1)

            users_with_approval = [u for u in duplicates if u.approvals.exists()]

            # Ensure all users have the same birthdate.
            assert all(user.birthdate == duplicates[0].birthdate for user in duplicates)

            nirs = [u.jobseeker_profile.nir for u in duplicates if u.jobseeker_profile.nir]
            if len(nirs) > 1:
                self.NIR_DUPLICATES_COUNT += 1
                self.handle_nir_duplicates(duplicates)
                continue

            # Easy cases.
            # None or 1 PASS IAE was issued for the same person with multiple accounts.
            if len(users_with_approval) <= 1:
                self.EASY_DUPLICATES_COUNT += 1
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

                self.handle_easy_duplicates(duplicates, target=target, nirs=nirs)

            # Hard cases.
            # More than one PASS IAE was issued for the same person.
            elif len(users_with_approval) > 1:
                self.HARD_DUPLICATES_COUNT += 1
                self.handle_hard_duplicates(duplicates)

        if not self.no_xlsx:
            self.to_xlsx(
                "easy-duplicates",
                [
                    "Compte de destination",
                    "URL admin du compte de destination",
                    "Nombre de doublons",
                    "Doublons fusionnés",
                ],
                self.EASY_DUPLICATES_LOGS,
            )
            self.to_xlsx(
                "hard-duplicates",
                [
                    "Numéro",  # Lines with the same number are duplicates.
                    "Nombre de doublons",
                    "Email",
                    "NIR",
                    "Date de naissance",
                    "Numéro PASS IAE",
                    "Début PASS IAE",
                    "Fin PASS IAE",
                    "Lien admin PASS IAE",
                    "Candidatures récentes (< 3 mois)",
                ],
                self.HARD_DUPLICATES_LOGS,
            )
            self.to_xlsx(
                "nir-duplicates",
                [
                    "Numéro",  # Lines with the same number are duplicates.
                    "Nombre de doublons",
                    "Email",
                    "NIR",
                ],
                self.NIR_DUPLICATES_LOGS,
            )

        self.stdout.write("-" * 80)
        self.stdout.write(f"{self.EASY_DUPLICATES_COUNT} easy duplicates merged.")
        self.stdout.write(f"{self.HARD_DUPLICATES_COUNT} hard duplicates found.")
        self.stdout.write(f"{self.NIR_DUPLICATES_COUNT} NIR duplicates found.")

        self.stdout.write("-" * 80)
        self.stdout.write("Done!")

    def to_xlsx(self, filename, fieldnames, data):
        log_datetime = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        filename = f"{log_datetime}-{filename}-{settings.ITOU_ENVIRONMENT.lower()}.xlsx"
        self.export_to_xlsx(filename, fieldnames, data)
