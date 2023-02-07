import io
from datetime import datetime as dt

import pandas
from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.utils import timezone

from itou.approvals.models import Approval, Suspension


FIRST_SCRIPT_RUNNING_DATE = timezone.make_aware(dt(2023, 2, 1, 17, 44))
MONTHS_OF_PROLONGATION = 24


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--wet-run", action="store_true", dest="wet_run")
        parser.add_argument(
            "--file-path",
            dest="file_path",
            required=True,
            action="store",
            help="Path of the ASP CSV file to deduplicate",
        )

    def clean_file(self, file_path):
        with open(file_path, newline="", encoding="utf-8") as input_file:
            output_file = io.StringIO()
            for line in input_file:
                if not line.strip("\n").startswith("\t! skipping "):
                    output_file.write(line)
        output_file.seek(0)
        return output_file

    def handle(self, file_path, wet_run=False, **options):
        max_threshold = dt.today() + relativedelta(months=Suspension.MAX_DURATION_MONTHS)
        suspensions = Suspension.objects.filter(end_at__gte=max_threshold)
        self.stdout.write(f"Problematic suspensions found in database: {suspensions.count()}.")

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
        excluded_suspensions = suspensions.exclude(approval__number__in=unique_approval_numbers_from_file)
        for suspension in excluded_suspensions:
            self.stdout.write(
                "Suspension not in log file. "
                f"Pk: {suspension.pk}, start_at: {suspension.start_at}, end_at: {suspension.end_at}"
            )

        suspensions = suspensions.filter(approval__number__in=unique_approval_numbers_from_file)
        self.stdout.write(f"Problematic suspensions found in input file: {suspensions.count()}")

        # Count duplicated lines.
        # Generated dataframe:
        #               approval_number  size
        #        35509  9999922919054    4
        df = df.groupby(by="approval_number", as_index=False).size().sort_values("size")

        updated_suspensions_counter = 0
        skipped_suspensions_no_duplicate_counter = 0
        skipped_suspensions_other_reason_counter = 0
        for _, row in df.iterrows():
            # Only approvals with several suspensions have caused troubles.
            if row["size"] == 1:
                skipped_suspensions_no_duplicate_counter += 1
                continue

            try:
                approval = Approval.objects.get(number=row["approval_number"])
            except Approval.DoesNotExist:
                self.stdout.write(f"Skipping approval not found: {row['approval_number']}")
                skipped_suspensions_other_reason_counter += 1
                continue

            last_suspension = approval.suspension_set.order_by("end_at").last()
            # Don't update suspensions updated by a user after the first script ran.
            if last_suspension.updated_at and last_suspension.updated_at > FIRST_SCRIPT_RUNNING_DATE:
                self.stdout.write(
                    "Skipping suspension updated after script ran: "
                    f"{last_suspension.pk}, start_at: {last_suspension.start_at}, end_at: {last_suspension.end_at}, "
                    f"updated_at: {last_suspension.updated_at.date()}"
                )
                skipped_suspensions_other_reason_counter += 1
                continue

            last_suspension.end_at -= relativedelta(months=MONTHS_OF_PROLONGATION * (row["size"] - 1))
            try:
                last_suspension.clean()
                updated_suspensions_counter += 1
            except ValidationError as error:
                self.stdout.write("; ".join(error.messages))
                self.stdout.write(
                    (
                        f">  Skipping because of validation error! Suspension: {last_suspension.pk}, "
                        f"Approval number: {row['approval_number']}"
                    )
                )
                self.stdout.write(f"start_at: {last_suspension.start_at}, end_at: {last_suspension.end_at}")
                skipped_suspensions_other_reason_counter += 1
                continue

            if wet_run:
                last_suspension.save(update_fields=["end_at", "updated_at"])
        self.stdout.write(f"Updated suspensions: {updated_suspensions_counter}")
        self.stdout.write(
            f"Skipped suspensions (one suspension per approval): {skipped_suspensions_no_duplicate_counter}"
        )
        self.stdout.write(f"Skipped suspensions (other reasons): {skipped_suspensions_other_reason_counter}")
