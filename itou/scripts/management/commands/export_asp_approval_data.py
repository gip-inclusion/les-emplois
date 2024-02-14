import csv
from io import StringIO
from os.path import splitext

import django.db.models as models

from itou.approvals.models import Approval
from itou.utils.command import BaseCommand


CSV_SEPARATOR = ";"
FILENAME_SUFFIX = "_updated"


class ItouHashError(Exception):
    pass


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "--file-path",
            dest="file_path",
            required=True,
            action="store",
            help="Path of the ASP CSV file to augment",
        )
        parser.add_argument("--wet-run", action="store_true", dest="wet_run")

    def handle(self, file_path, *, wet_run, **options):
        nb_unknown_approval_errors = 0
        nb_unknown_user_errors = 0
        nb_unknown_errors = 0
        nb_ok_records = 0
        end_dates = []

        self.stdout.write("Augment ASP data file with the end date of approval if it has changed")
        self.stdout.write(f"params: {file_path=}, {wet_run=}")

        def check_id_itou(approval: Approval, id_itou: str):
            actual_hash_id = approval.user.jobseeker_profile.asp_uid
            if actual_hash_id != id_itou:
                raise ItouHashError(f"User hash ids don't match {id_itou=} {actual_hash_id=}")

        def get_end_date_column_value(approval, end_date):
            approval_date_as_str = f"{approval.end_at:%Y-%m-%d}"
            return None if approval_date_as_str == end_date else approval_date_as_str

        def append_new_dates_to_file(file_path, end_dates):
            filename, ext = splitext(file_path)
            new_filename = f"{filename}{FILENAME_SUFFIX}{ext}"
            with open(file_path) as input_file:
                with open(new_filename, "w") if wet_run else StringIO() as output_file:
                    for line, end_date in zip(input_file, end_dates):
                        new_line = line.rstrip() + f"{end_date}\n" if end_date else line
                        output_file.write(new_line)
            return new_filename

        with open(file_path) as input_file:
            reader = csv.reader(input_file, delimiter=CSV_SEPARATOR)
            for line_number, (id_itou, _, _, approval_number, _, end_date, _) in enumerate(reader, 1):
                try:
                    approval = Approval.objects.select_related("user__jobseeker_profile").get(number=approval_number)
                    check_id_itou(approval, id_itou)
                    new_end_date = get_end_date_column_value(approval, end_date)
                except models.ObjectDoesNotExist:
                    end_dates.append(None)
                    nb_unknown_approval_errors += 1
                    self.stdout.write(f"{line_number=}: approval does not exist: {approval_number=}")
                except ItouHashError as ex:
                    end_dates.append(None)
                    nb_unknown_user_errors += 1
                    self.stdout.write(f"{line_number=}: approval {approval_number}: {ex}")
                except Exception as ex:
                    end_dates.append(None)
                    nb_unknown_errors += 1
                    self.stdout.write(f"{line_number=}: unknown error occured : {ex=}")
                else:
                    if new_end_date:
                        nb_ok_records += 1
                    end_dates.append(new_end_date)

        # Creating new export file
        result_file = append_new_dates_to_file(file_path, end_dates)

        self.stdout.write(f"Errors: {nb_unknown_approval_errors=} {nb_unknown_user_errors=} {nb_unknown_errors=}")
        self.stdout.write(f"Successfully updated {nb_ok_records} records with new approval end date")
        self.stdout.write(f"Result in: {result_file}")
