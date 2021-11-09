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
        django-admin deduplicate_job_seekers --dry-run

    To merge duplicates job seekers in the database:
        django-admin deduplicate_job_seekers
    """

    help = "Deduplicate job seekers."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Only display data to deduplicate")

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

    def merge_easy_cases(self, duplicates, target):
        """
        Merge easy cases: when None or 1 PASS IAE was issued accross multiple accounts.
        """

        assert target.email

        users_to_delete = [u for u in duplicates if u != target]

        user_admin_path = reverse("admin:users_user_change", args=[target.pk])
        user_admin_url = f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}{user_admin_path}"
        self.logger.debug("<tr>")
        self.logger.debug(f'<td><a href="{user_admin_url}">{target.email}</a></td>')
        self.logger.debug(f"<td>{len(users_to_delete)}</td>")
        self.logger.debug(f"<td>{' ; '.join([u.email for u in users_to_delete])}</td>")
        self.logger.debug("</tr>")

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

    def handle(self, dry_run=False, **options):

        self.set_logger(options.get("verbosity"))

        self.dry_run = dry_run

        self.logger.debug("Starting. Good luck…")

        count_easy_cases = 0
        count_hard_cases = 0
        hard_cases = []

        duplicates_dict = User.objects.get_duplicates_by_pole_emploi_id(
            prefetch_related_lookups=["approvals", "eligibility_diagnoses"]
        )

        self.logger.debug("<table>")
        self.logger.debug("<thead>")
        self.logger.debug("<tr>")
        self.logger.debug("<th>Compte de destination</th>")
        self.logger.debug("<th>Nombre de doublons</th>")
        self.logger.debug("<th>Doublons</th>")
        self.logger.debug("</tr>")
        self.logger.debug("</thead>")
        self.logger.debug("<tbody>")

        for pe_id, duplicates in duplicates_dict.items():

            users_with_approval = [u for u in duplicates if u.approvals.exists()]

            # Ensure all users have the same birthdate.
            assert all(user.birthdate == duplicates[0].birthdate for user in duplicates)

            # Easy cases.
            # None or 1 PASS IAE was issued for the same person with multiple accounts.
            if len(users_with_approval) <= 1:

                count_easy_cases += 1

                user_with_approval = next((u for u in duplicates if u.approvals.exists()), None)

                # Give priority to the user with a PASS IAE.
                if user_with_approval:
                    self.merge_easy_cases(duplicates, target=user_with_approval)

                # Handle duplicates without any PASS IAE.
                else:

                    # Give priority to the first user who already logged in.
                    first_autonomous_user = next((u for u in duplicates if u.last_login), None)
                    if first_autonomous_user:
                        self.merge_easy_cases(duplicates, target=first_autonomous_user)

                    # Choose an arbitrary user to merge others into.
                    else:
                        self.merge_easy_cases(duplicates, target=duplicates[0])

            # Hard cases.
            # More than one PASS IAE was issued for the same person.
            # We only display logs for the moment, we don't know yet how to merge them.
            elif len(users_with_approval) > 1:
                count_hard_cases += 1
                hard_cases.append(duplicates)

        self.logger.debug("</tbody></table>")

        self.logger.debug("-" * 80)
        self.logger.debug(f"{count_easy_cases} easy cases merged.")

        self.log_hard_cases(count_hard_cases, hard_cases)

        self.logger.debug("-" * 80)
        self.logger.debug("Done.")

    def log_hard_cases(self, count_hard_cases, hard_cases):
        self.logger.debug("-" * 80)
        self.logger.debug(f"{count_hard_cases} hard cases with more than one PASS IAE issued for the same person:")
        self.logger.debug("<table>")
        self.logger.debug("<thead>")
        self.logger.debug("<tr>")
        self.logger.debug("<th>Numéro</th>")
        self.logger.debug("<th>Nombre de doublons</th>")
        self.logger.debug("<th>Email</th>")
        self.logger.debug("<th>Numéro PASS IAE</th>")
        self.logger.debug("<th>Début PASS IAE</th>")
        self.logger.debug("<th>Fin PASS IAE</th>")
        self.logger.debug("</tr>")
        self.logger.debug("</thead>")
        self.logger.debug("<tbody>")
        for i, duplicates in enumerate(hard_cases, 1):
            for u in duplicates:
                self.logger.debug("<tr>")
                self.logger.debug(f"<td>{i}</td>")
                self.logger.debug(f"<td>{len(duplicates)}</td>")
                user_admin_path = reverse("admin:users_user_change", args=[u.pk])
                user_admin_url = f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}{user_admin_path}"
                debug_msg = f'<td><a href="{user_admin_url}">{u.email}</a></td>'
                if approval := u.approvals.last():
                    approval_admin_path = reverse("admin:approvals_approval_change", args=[approval.pk])
                    approval_admin_url = f"{settings.ITOU_PROTOCOL}://{settings.ITOU_FQDN}{approval_admin_path}"
                    debug_msg += f'<td><a href="{approval_admin_url}">{approval.number}</a> </td>'
                    debug_msg += f"<td>{approval.start_at.strftime('%d/%m/%Y')}</td>"
                    debug_msg += f"<td>{approval.end_at.strftime('%d/%m/%Y')}</td>"
                else:
                    debug_msg += '<td colspan="3"> </td>'
                self.logger.debug(debug_msg)
                self.logger.debug("</tr>")
        self.logger.debug("</tbody></table>")
