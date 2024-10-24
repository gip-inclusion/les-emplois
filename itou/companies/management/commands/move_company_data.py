import argparse

from django.db import transaction
from django.utils import timezone

from itou.approvals import models as approvals_models
from itou.companies import models as companies_models
from itou.eligibility import models as eligibility_models
from itou.employee_record.models import EmployeeRecord
from itou.invitations import models as invitations_models
from itou.job_applications import models as job_applications_models
from itou.siae_evaluations.models import EvaluatedSiae
from itou.users import models as users_models
from itou.utils.command import BaseCommand


HELP_TEXT = """
    Move all data from company A to company B (or only the job applications if `only-job-applications` option is set).
    After this move compay A is no longer supposed to be used or even accessible.
    Members of company A are detached, geolocalization is removed and new job applications are blocked.

    This command should be used when users have been using the wrong company A instead of using the correct company B.

    COmpany A is *not* deleted at the end. This is because it might not always be possible or make sense to do so
    and because cleaning up irrelevant companies is actually the job of the import_siae command.

    You will most likely still have manual actions to do after the move, typically deactivating the convention
    of company A. That one cannot be automated because it has drastic consequences as it disables all companies of the
    same convention. So be sure to read your trello ticket instructions thoroughly and don't assume this command
    does everything.

    Examples of use in local dev:
    $ make mgmt_cmd COMMAND="move_company_data --from 3243 --to 9612"
    $ make mgmt_cmd COMMAND="move_company_data --from 3243 --to 9612 --only-job-applications"

    And in production:
    $ cd && cd app_* && django-admin move_company_data --from 3243 --to 9612 --wet-run
"""


class Command(BaseCommand):
    help = HELP_TEXT

    def add_arguments(self, parser):
        parser.add_argument(
            "--from",
            dest="from_id",
            metavar="FROM",
            type=int,
            help="ID of the company to move data from.",
            required=True,
        )
        parser.add_argument(
            "--to",
            dest="to_id",
            metavar="TO",
            type=int,
            help="ID of the the company to move data to.",
            required=True,
        )
        parser.add_argument(
            "--ignore-siae-evaluations",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="Set to True to move company data despite the <FROM> company having an SIAE evaluation.",
        )
        parser.add_argument(
            "--preserve-to-company-data",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="Do not override <TO> company brand, description and phone with <FROM> data.",
        )
        parser.add_argument(
            "--only-job-applications",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="Set to True to move only job applications, nothing else!",
        )
        parser.add_argument("--wet-run", action=argparse.BooleanOptionalAction, default=False)

    def handle(
        self,
        from_id,
        to_id,
        *,
        wet_run,
        ignore_siae_evaluations,
        only_job_applications,
        preserve_to_company_data,
        **options,
    ):
        if from_id == to_id:
            self.stderr.write(f"Unable to use the same company as source and destination (ID {from_id})\n")
            return

        from_company_qs = companies_models.Company.objects.filter(pk=from_id)
        try:
            from_company = from_company_qs.get()
        except companies_models.Company.DoesNotExist:
            self.stderr.write(f"Unable to find the company ID {from_id}\n")
            return
        if not ignore_siae_evaluations and EvaluatedSiae.objects.filter(siae=from_company).exists():
            self.stderr.write(
                f"Cannot move data for company ID {from_id}, it has an SIAE evaluation object. "
                "Double check the procedure with the support team."
            )
            return

        to_company_qs = companies_models.Company.objects.filter(pk=to_id)
        try:
            to_company = to_company_qs.get()
        except companies_models.Company.DoesNotExist:
            self.stderr.write(f"Unable to find the company ID {to_id}\n")
            return

        # Intermediate variable for better readability
        move_all_data = not only_job_applications

        self.stdout.write(
            "MOVE {} OF company.id={} - {} {} - {}\n".format(
                "DATA" if move_all_data else "JOB APPLICATIONS",
                from_company.pk,
                from_company.kind,
                from_company.siret,
                from_company.display_name,
            )
        )

        job_applications_sent = job_applications_models.JobApplication.objects.filter(sender_company_id=from_id)
        self.stdout.write(f"| Job applications sent: {job_applications_sent.count()}")

        job_applications_received = job_applications_models.JobApplication.objects.filter(to_company_id=from_id)
        self.stdout.write(f"| Job applications received: {job_applications_received.count()}")

        employee_records_created_count = EmployeeRecord.objects.filter(job_application__to_company_id=from_id).count()
        self.stdout.write(f"| Employee records created: {employee_records_created_count}")

        if move_all_data:
            job_descriptions = companies_models.JobDescription.objects.filter(company_id=from_id)
            self.stdout.write(f"| Job descriptions: {job_descriptions.count()}\n")

            # Move users not already present in company destination
            members = companies_models.CompanyMembership.objects.filter(company_id=from_id).exclude(
                user__in=users_models.User.objects.filter(companymembership__company_id=to_id)
            )
            self.stdout.write(f"| Members: {members.count()}\n")

            diagnoses = eligibility_models.EligibilityDiagnosis.objects.filter(author_siae_id=from_id)
            self.stdout.write(f"| Diagnoses: {diagnoses.count()}\n")

            prolongations = approvals_models.Prolongation.objects.filter(declared_by_siae_id=from_id)
            self.stdout.write(f"| Prolongations: {prolongations.count()}\n")

            suspensions = approvals_models.Suspension.objects.filter(siae_id=from_id)
            self.stdout.write(f"| Suspensions: {suspensions.count()}\n")

            # Don't move invitations for existing members
            # The goal is to keep information about the original information
            invitations = invitations_models.EmployerInvitation.objects.filter(company_id=from_id).exclude(
                email__in=users_models.User.objects.filter(companymembership__company_id=to_id).values_list(
                    "email", flat=True
                )
            )
            self.stdout.write(f"| Invitations: {invitations.count()}\n")

        self.stdout.write(
            f"INTO company.id={to_company.pk} - {to_company.kind} {to_company.siret} - {to_company.display_name}\n"
        )

        dest_company_job_applications_sent = job_applications_models.JobApplication.objects.filter(
            sender_company_id=to_id
        )
        self.stdout.write(f"| Job applications sent: {dest_company_job_applications_sent.count()}\n")

        dest_company_job_applications_received = job_applications_models.JobApplication.objects.filter(
            to_company_id=to_id
        )
        self.stdout.write(f"| Job applications received: {dest_company_job_applications_received.count()}\n")

        dest_employee_records_created_count = EmployeeRecord.objects.filter(
            job_application__to_company_id=to_id
        ).count()
        self.stdout.write(f"| Employee records created: {dest_employee_records_created_count}")

        if move_all_data and not preserve_to_company_data:
            self.stdout.write(f"| Brand '{to_company.brand}' will be updated with '{from_company.display_name}'\n")
            self.stdout.write(
                f"| Description \n{to_company.description}\nwill be updated with\n{from_company.description}\n"
            )
            self.stdout.write(f"| Phone '{to_company.phone}' will be updated with '{from_company.phone}'\n")

        if not wet_run:
            self.stdout.write("Nothing to do in dry run mode.\n")
            return

        with transaction.atomic():
            # If we move the job applications without moving the job descriptions as well, we need to unlink them,
            # as job applications will be attached to company B but job descriptions will stay attached to company A.
            if only_job_applications:
                for job_application in job_applications_sent:
                    job_application.selected_jobs.clear()
                for job_application in job_applications_received:
                    job_application.selected_jobs.clear()

            job_applications_sent.update(sender_company_id=to_id)
            job_applications_received.update(to_company_id=to_id)

            if move_all_data:
                job_descriptions.update(company_id=to_id)
                members.update(company_id=to_id)
                diagnoses.update(author_siae_id=to_id)
                prolongations.update(declared_by_siae_id=to_id)
                suspensions.update(siae_id=to_id)
                invitations.update(company_id=to_id)
                if not preserve_to_company_data:
                    to_company_qs.update(
                        brand=from_company.display_name,
                        description=from_company.description,
                        phone=from_company.phone,
                        is_searchable=True,  # Make sure the new company appears in results
                    )
                from_company_qs.update(
                    block_job_applications=True,
                    job_applications_blocked_at=timezone.now(),
                    is_searchable=False,  # Make sure the old company no longer appears in results
                )

        self.stdout.write(
            "MOVE {} OF company.id={} FINISHED\n".format(
                "DATA" if move_all_data else "JOB APPLICATIONS", from_company.pk
            )
        )
        orig_job_applications_sent = job_applications_models.JobApplication.objects.filter(sender_company_id=from_id)
        self.stdout.write(f"| Job applications sent: {orig_job_applications_sent.count()}\n")

        orig_job_applications_received = job_applications_models.JobApplication.objects.filter(to_company_id=from_id)
        self.stdout.write(f"| Job applications received: {orig_job_applications_received.count()}\n")

        orig_employee_records = EmployeeRecord.objects.filter(job_application__to_company_id=from_id)
        self.stdout.write(f"| Employee records created: {orig_employee_records.count()}")

        self.stdout.write(f"INTO company.id={to_company.pk}\n")

        dest_company_job_applications_sent = job_applications_models.JobApplication.objects.filter(
            sender_company_id=to_id
        )
        self.stdout.write(f"| Job applications sent: {dest_company_job_applications_sent.count()}\n")

        dest_company_job_applications_received = job_applications_models.JobApplication.objects.filter(
            to_company_id=to_id
        )
        self.stdout.write(f"| Job applications received: {dest_company_job_applications_received.count()}\n")

        dest_employee_records = EmployeeRecord.objects.filter(job_application__to_company_id=to_id)
        self.stdout.write(f"| Employee records created: {dest_employee_records.count()}")
