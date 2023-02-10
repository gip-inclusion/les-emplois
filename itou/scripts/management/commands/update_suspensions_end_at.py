import io
from datetime import date, datetime, timedelta

import pandas
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from itou.approvals.models import Approval, Suspension


FIRST_SCRIPT_RUNNING_DATE = datetime(2023, 2, 1, 16, 44, tzinfo=timezone.utc)
MONTHS_OF_PROLONGATION = 24


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            dest="file_path",
            action="store",
            help="Path of the ASP CSV file to deduplicate",
        )
        parser.add_argument("--wet-run", action="store_true", dest="wet_run")

    def clean_file(self, file_path):
        with open(file_path) as input_file:
            output_file = io.StringIO()
            for line in input_file:
                if not line.startswith("\t! skipping "):
                    output_file.write(line)
        output_file.seek(0)
        return output_file

    @transaction.atomic()
    def handle(self, file_path, wet_run=False, **options):
        max_threshold = timedelta(365 * Suspension.MAX_DURATION_MONTHS / 12)
        suspensions = Suspension.objects.filter(end_at__gt=F("start_at") + max_threshold)
        self.stdout.write(f"Problematic suspensions found in database: {suspensions.count()}")

        csv_file = self.clean_file(file_path)
        colnames = ["approval_number", "suspension_start_at", "suspension_end_at"]
        converters = {
            "approval_number": str,
            "suspensions_start_at": pandas.to_datetime,
            "suspensions_end_at": pandas.to_datetime,
        }
        df = pandas.read_csv(csv_file, sep=" ", names=colnames, header=None, converters=converters)

        unique_approval_numbers_from_file = set(df["approval_number"].to_list())
        self.stdout.write(f"Total of unique approvals in input file: {len(unique_approval_numbers_from_file)}")

        # Just for the records as we only have one.
        # Should be treated manually.
        suspensions_not_in_file = suspensions.exclude(approval__number__in=unique_approval_numbers_from_file)
        for suspension in suspensions_not_in_file:
            self.stdout.write(
                "Suspension not in log file : "
                f"pk={suspension.pk} start_at={suspension.start_at} end_at={suspension.end_at}"
            )

        suspensions = suspensions.filter(approval__number__in=unique_approval_numbers_from_file)
        self.stdout.write(f"Problematic suspensions found in input file: {suspensions.count()}")

        # Count duplicated lines.
        # Generated dataframe:
        #               approval_number  size
        #        35509  9999922919054    4
        df_gouped = df.groupby(by="approval_number", as_index=False).size().sort_values("size")
        # Only keep lines with more the one value
        df_gouped = df_gouped[df_gouped["size"] > 1]
        self.stdout.write(f"Anomalies found in input file: {len(df_gouped)}")

        self.stdout.write("")
        self.stdout.write("Start processing")
        self.stdout.write("========================================")
        updated_suspensions_counter = 0
        skipped_suspensions_other_reason_counter = 0
        for _, row in df_gouped.iterrows():
            try:
                approval = Approval.objects.get(number=row["approval_number"])
            except Approval.DoesNotExist:
                self.stdout.write(f"Skipping approval not found: approval={row['approval_number']}")
                skipped_suspensions_other_reason_counter += 1
                continue

            last_suspension = approval.suspension_set.order_by("end_at").last()
            theorical_suspension_end = max(df[df["approval_number"] == approval.number]["suspension_end_at"])
            # Don't update suspensions updated by a user after the first script ran.
            if str(last_suspension.end_at) != theorical_suspension_end:
                updated_at = last_suspension.updated_at.date() if last_suspension.updated_at else "None"
                self.stdout.write(
                    "Skipping suspension updated after script ran: "
                    f"pk={last_suspension.pk} start_at={last_suspension.start_at} end_at={last_suspension.end_at} "
                    f"updated_at={updated_at}"
                )
                skipped_suspensions_other_reason_counter += 1
                if last_suspension.end_at > Suspension.get_max_end_at(last_suspension.start_at):
                    self.stdout.write(">  Still to long though !")
                continue

            previous_end_at = last_suspension.end_at
            last_suspension.end_at = date.fromisoformat(
                min(df[df["approval_number"] == approval.number]["suspension_end_at"])
            )

            try:
                last_suspension.clean()
                if last_suspension.end_at != Suspension.get_max_end_at(last_suspension.start_at):
                    self.stdout.write(
                        f"Updated suspension isn't 36 month long. Is it normal ? "
                        f"pk={last_suspension.pk} start_at={last_suspension.start_at} end_at={last_suspension.end_at} "
                    )
                updated_suspensions_counter += 1
            except ValidationError as error:
                self.stdout.write("; ".join(error.messages))
                self.stdout.write(
                    (
                        f">  Skipping because of validation error! Suspension pk={last_suspension.pk} "
                        f"approval={row['approval_number']} start_at={last_suspension.start_at} "
                        f"end_at={last_suspension.end_at}"
                    )
                )
                skipped_suspensions_other_reason_counter += 1
            else:
                self.stdout.write(
                    (
                        f"Updating suspension pk={last_suspension.pk} approval={row['approval_number']} "
                        f"start_at={last_suspension.start_at} "
                        f"old_end_at={previous_end_at} new_end_at={last_suspension.end_at}"
                    )
                )
                if wet_run:
                    last_suspension.save(update_fields=["end_at", "updated_at"])

        self.stdout.write("")
        self.stdout.write("Results")
        self.stdout.write("========================================")
        self.stdout.write(f"Updated suspensions: {updated_suspensions_counter}")
        self.stdout.write(f"Skipped suspensions (see reasons above): {skipped_suspensions_other_reason_counter}")

        if updated_suspensions_counter + skipped_suspensions_other_reason_counter != len(df_gouped):
            self.stdout.write("Some suspensions were not updated or skipped !!")
        else:
            self.stdout.write("Everything is good")
