import argparse

from django.db import transaction

from itou.companies import models as companies_models, transfer
from itou.utils.command import BaseCommand


HELP_TEXT = """
    Move all data from company A to company B (or only the job applications if `only-job-applications` option is set).
    After this move company A is no longer supposed to be used or even accessible.
    Members of company A are detached, geolocalization is removed and new job applications are blocked.

    This command should be used when users have been using the wrong company A instead of using the correct company B.

    Company A is *not* deleted at the end. This is because it might not always be possible or make sense to do so
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


class DryRunException(Exception):
    """Used to rollback database changes"""


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

        to_company_qs = companies_models.Company.objects.filter(pk=to_id)
        try:
            to_company = to_company_qs.get()
        except companies_models.Company.DoesNotExist:
            self.stderr.write(f"Unable to find the company ID {to_id}\n")
            return

        # Intermediate variable for better readability
        move_all_data = not only_job_applications

        if only_job_applications:
            fields_to_transfer = [
                transfer.TransferField.JOB_APPLICATIONS_RECEIVED,
                transfer.TransferField.JOB_APPLICATIONS_SENT,
            ]
        elif preserve_to_company_data:
            fields_to_transfer = [
                transfer_field
                for transfer_field in transfer.TransferField
                if not transfer.TRANSFER_SPECS[transfer_field].get("model_field")
            ]
        else:
            fields_to_transfer = list(transfer.TransferField)

        self.stdout.write(
            "MOVE {} OF company.id={} - {} {} - {}\n".format(
                "DATA" if move_all_data else "JOB APPLICATIONS",
                from_company.pk,
                from_company.kind,
                from_company.siret,
                from_company.display_name,
            )
        )
        for field_to_transfer in fields_to_transfer:
            spec = transfer.TRANSFER_SPECS[field_to_transfer]
            if "model_field" in spec:
                continue
            all_items_count = transfer.get_transfer_queryset(from_company, None, spec).count()
            to_transfer_count = transfer.get_transfer_queryset(from_company, to_company, spec).count()
            suffix = f" (dont {to_transfer_count} à transférer)" if to_transfer_count != all_items_count else ""
            self.stdout.write(f"| {field_to_transfer.label}: {all_items_count}{suffix}\n")

        self.stdout.write(
            f"INTO company.id={to_company.pk} - {to_company.kind} {to_company.siret} - {to_company.display_name}\n"
        )
        for field_to_transfer in fields_to_transfer:
            spec = transfer.TRANSFER_SPECS[field_to_transfer]
            if "model_field" in spec:
                continue
            all_items_count = transfer.get_transfer_queryset(to_company, None, spec).count()
            self.stdout.write(f"| {field_to_transfer.label}: {all_items_count}\n")

        self.stdout.write("Rapport du transfert:\n")
        disable_from_company = not only_job_applications
        try:
            with transaction.atomic():
                reporter = transfer.transfer_company_data(
                    from_company,
                    to_company,
                    fields_to_transfer,
                    disable_from_company=disable_from_company,
                    ignore_siae_evaluations=ignore_siae_evaluations,
                )
                for section, section_changes in reporter.changes.items():
                    if transfer.TRANSFER_SPECS.get(section, {}).get("model_field"):
                        self.stdout.write(
                            f"| {section.label}: {section_changes[0] if section_changes else 'Pas de changement'}"
                        )
                    else:
                        self.stdout.write(f"| {section.label}: {len(section_changes)}")
                        if wet_run:
                            # Print more info to help a possible rollback
                            for section_change in section_changes:
                                self.stdout.write(f"| - {section_change}")

                if not wet_run:
                    raise DryRunException("Rollback!")
        except transfer.TransferError as e:
            self.stderr.write(e.args[0])
        except DryRunException:
            self.stdout.write("Transfer rolled back in dry run mode.\n")
            return
