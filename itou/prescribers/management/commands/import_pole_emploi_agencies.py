import csv
import logging

from itou.common_apps.address.departments import DEPARTMENTS, department_from_postcode
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.models import PrescriberOrganization
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    """
    Import Pole emploi agencies (prescriber organizations) data into
    the database.
    This command is meant to be used before any fixture is available.

    To debug:
        django-admin import_pole_emploi_agencies --dry-run path_to_file.csv
        django-admin import_pole_emploi_agencies --dry-run --verbosity=2 path_to_file.csv

    To populate the database:
        django-admin import_pole_emploi_agencies path_to_file.csv
    """

    help = "Import the content of the prescriber organizations csv file into the database."

    def add_arguments(self, parser):
        parser.add_argument("path_to_file", type=str)
        parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Only print data to import")

    def set_logger(self, verbosity):
        """
        Set logger level based on the verbosity option.
        """
        handler = logging.StreamHandler(self.stdout)

        self.logger = logging.getLogger(__name__)
        self.logger.propagate = False
        self.logger.addHandler(handler)

        self.logger.setLevel(logging.INFO)
        if verbosity > 1:
            self.logger.setLevel(logging.DEBUG)

    def handle(self, path_to_file, *, dry_run, **options):
        self.set_logger(options.get("verbosity"))

        with open(path_to_file) as csvfile:
            # Count lines in CSV.
            reader = csv.reader(csvfile, delimiter=",")
            row_count = sum(1 for row in reader)
            last_progress = 0
            # Reset the iterator to iterate through the reader again.
            csvfile.seek(0)

            for i, row in enumerate(reader):
                if i == 0:
                    # Skip CSV header.
                    continue

                progress = int((100 * i) / row_count)
                if progress > last_progress + 5:
                    self.stdout.write(f"Creating prescriber organizations… {progress}%")
                    last_progress = progress

                # SAFIR code is mandatory for security reasons
                code_safir = row[0].strip()
                if not code_safir:
                    self.stdout.write(f"No SAFIR code provided for line {i}")
                    continue
                assert code_safir.isdigit()
                assert len(code_safir) == 5

                agency_kind = row[1].strip()
                name = row[2].strip()
                address_line_1 = row[4].strip()
                address_line_2 = row[3].strip()
                post_code = row[5].strip()
                city = row[6].strip()

                self.logger.debug("-" * 80)

                if agency_kind == "APE" or name.upper().startswith("DT"):
                    name = f"Pôle emploi - {name.upper()}"
                else:
                    name = f"Pôle emploi - {agency_kind} {name.upper()}"

                self.logger.debug(name)
                self.logger.debug(code_safir)
                self.logger.debug(address_line_1)
                self.logger.debug(address_line_2)
                self.logger.debug(city)
                self.logger.debug(post_code)

                # See address.utils.departement
                department = department_from_postcode(post_code)

                self.logger.debug(department)
                assert department in DEPARTMENTS

                existing_org = PrescriberOrganization.objects.filter(code_safir_pole_emploi=code_safir)

                if existing_org.exists():
                    self.stdout.write(f"Skipping line {i} ({name}) because an organization with")
                    self.stdout.write(f"the following SAFIR already exists: {code_safir}.")
                    continue

                if not dry_run:
                    pe_kind = PrescriberOrganizationKind.PE

                    org, _created = PrescriberOrganization.objects.get_or_create(
                        code_safir_pole_emploi=code_safir,
                        kind=pe_kind,
                        defaults={
                            "is_authorized": True,
                            "name": name,
                            "address_line_1": address_line_1,
                            "address_line_2": address_line_2,
                            "post_code": post_code,
                            "city": city,
                            "department": department,
                        },
                    )

                    org.set_coords(address=org.address_line_1, post_code=org.post_code)
                    org.save()
                    self.logger.debug("%s created.", org.display_name)

        self.stdout.write("-" * 80)
        self.stdout.write("Done.")
