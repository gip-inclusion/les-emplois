import argparse

from django.db import transaction
from itoutils.django.commands import dry_runnable

from itou.common_apps.organizations import transfer
from itou.prescribers import models as prescribers_models
from itou.utils.command import BaseCommand


HELP_TEXT = """
    Move all data from prescriber organization A to prescriber organization B
    (or only the job applications if `only-job-applications` option is set).
    After this move prescriber organization A is no longer supposed to be used or even accessible.
    Members of prescriber organization A are detached and geolocalization is removed.

    This command should be used when users have been using the wrong prescriber organization A
    instead of using the correct prescriber organization B.

    Prescriber organization A is *not* deleted at the end. This is because it might not always be possible
    or make sense to do so.

    Examples of use in local dev:
    $ make mgmt_cmd COMMAND="move_prescriberorg_data --from 3243 --to 9612"
    $ make mgmt_cmd COMMAND="move_prescriberorg_data --from 3243 --to 9612 --only-job-applications"

    And in production:
    $ cd && cd app_* && django-admin move_prescriberorg_data --from 3243 --to 9612 --wet-run
"""


class Command(BaseCommand):
    help = HELP_TEXT
    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        parser.add_argument(
            "--from",
            dest="from_id",
            metavar="FROM",
            type=int,
            help="ID of the prescriber organization to move data from.",
            required=True,
        )
        parser.add_argument(
            "--to",
            dest="to_id",
            metavar="TO",
            type=int,
            help="ID of the the prescriber organization to move data to.",
            required=True,
        )
        parser.add_argument(
            "--preserve-to-org-data",
            action=argparse.BooleanOptionalAction,
            default=False,
            help=(
                "Do not override <TO> prescriber organization name, email, "
                "description, phone and website with <FROM> data."
            ),
        )
        parser.add_argument(
            "--only-job-applications",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="Set to True to move only job applications, nothing else!",
        )
        parser.add_argument("--wet-run", action=argparse.BooleanOptionalAction, default=False)

    @dry_runnable
    def handle(
        self,
        from_id,
        to_id,
        *,
        only_job_applications,
        preserve_to_org_data,
        **options,
    ):
        if from_id == to_id:
            self.stderr.write(
                f"Unable to use the same prescriber organization as source and destination (ID {from_id})\n"
            )
            return

        from_org_qs = prescribers_models.PrescriberOrganization.objects.filter(pk=from_id)
        try:
            from_org = from_org_qs.get()
        except prescribers_models.PrescriberOrganization.DoesNotExist:
            self.stderr.write(f"Unable to find the prescriber organization ID {from_id}\n")
            return

        to_org_qs = prescribers_models.PrescriberOrganization.objects.filter(pk=to_id)
        try:
            to_org = to_org_qs.get()
        except prescribers_models.PrescriberOrganization.DoesNotExist:
            self.stderr.write(f"Unable to find the prescriber organization ID {to_id}\n")
            return

        # Intermediate variable for better readability
        move_all_data = not only_job_applications

        if only_job_applications:
            fields_to_transfer = [transfer.TransferField.JOB_APPLICATIONS_SENT]
        elif preserve_to_org_data:
            fields_to_transfer = [
                transfer_field
                for transfer_field in transfer.PRESCRIBERORG_TRANSFER_FIELDS
                if not transfer.PRESCRIBERORG_TRANSFER_SPECS[transfer_field].get("model_field")
            ]
        else:
            fields_to_transfer = transfer.PRESCRIBERORG_TRANSFER_FIELDS

        self.stdout.write(
            "MOVE {} OF prescriberorganization.id={} - {} {} - {}\n".format(
                "DATA" if move_all_data else "JOB APPLICATIONS",
                from_org.pk,
                from_org.kind,
                from_org.siret,
                from_org.display_name,
            )
        )
        for field_to_transfer in fields_to_transfer:
            spec = transfer.PRESCRIBERORG_TRANSFER_SPECS[field_to_transfer]
            if "model_field" in spec:
                continue
            all_items_count = transfer.get_transfer_queryset(from_org, None, spec).count()
            to_transfer_count = transfer.get_transfer_queryset(from_org, to_org, spec).count()
            suffix = f" (dont {to_transfer_count} à transférer)" if to_transfer_count != all_items_count else ""
            self.stdout.write(f"| {field_to_transfer.label}: {all_items_count}{suffix}\n")

        self.stdout.write(
            f"INTO prescriberorganization.id={to_org.pk} - {to_org.kind} {to_org.siret} - {to_org.display_name}\n"
        )
        for field_to_transfer in fields_to_transfer:
            spec = transfer.PRESCRIBERORG_TRANSFER_SPECS[field_to_transfer]
            if "model_field" in spec:
                continue
            all_items_count = transfer.get_transfer_queryset(to_org, None, spec).count()
            self.stdout.write(f"| {field_to_transfer.label}: {all_items_count}\n")

        self.stdout.write("Rapport du transfert:\n")
        disable_from_org = not only_job_applications
        try:
            with transaction.atomic():
                reporter = transfer.transfer_org_data(
                    from_org,
                    to_org,
                    fields_to_transfer,
                    disable_from_org=disable_from_org,
                )
                for section, section_changes in reporter.changes.items():
                    if transfer.PRESCRIBERORG_TRANSFER_SPECS.get(section, {}).get("model_field"):
                        self.stdout.write(
                            f"| {section.label}: {section_changes[0] if section_changes else 'Pas de changement'}"
                        )
                    else:
                        self.stdout.write(f"| {section.label}: {len(section_changes)}")
                        # Print more info to help a possible rollback
                        for section_change in section_changes:
                            self.stdout.write(f"| - {section_change}")

        except transfer.TransferError as e:
            self.stderr.write(e.args[0])
