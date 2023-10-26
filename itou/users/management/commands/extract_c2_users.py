import csv
import datetime
import os

from django.conf import settings

from itou.common_apps.address.departments import DEPARTMENTS
from itou.institutions.enums import InstitutionKind
from itou.institutions.models import InstitutionMembership
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    """
    Extract all C2 users to CSV files, one file per category (DDETS IAE, DREETS IAE).

    To see how many records would be extracted without actually extracting them:
        django-admin extract_c2_users --no-csv

    To extract those records to CSV files:
        django-admin extract_c2_users
    """

    help = "Extract C2 users to CSV files."

    def add_arguments(self, parser):
        parser.add_argument("--no-csv", dest="no_csv", action="store_true", help="Do not export results in CSV")

    def to_csv(self, filename, data, description):
        if self.no_csv:
            self.stdout.write(f"{len(data)} {description} found but not exported.")
            return

        if len(data) == 0:
            self.stdout.write(f"No data found for {description} - SKIPPED.")
            return

        fieldnames = data[0].keys()
        log_datetime = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        os.makedirs(settings.EXPORT_DIR, exist_ok=True)
        path = f"{settings.EXPORT_DIR}/{log_datetime}-{filename}-{settings.ITOU_ENVIRONMENT.lower()}.csv"
        with open(path, "w") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            writer.writerows(data)
        self.stdout.write(f"Exported {len(data)} {description} to CSV file `{path}`")

    def get_basic_row(self, membership, org):
        user = membership.user
        return {
            "Email": user.email,
            "Prénom": user.first_name,
            "Nom": user.last_name,
            "Admin": "Oui" if membership.is_admin else "Non",
            "DateRattachement": membership.created_at.date(),
            "Département": DEPARTMENTS[org.department] if org.department else None,
            "Région": org.region,
        }

    def handle(self, *, no_csv, **options):
        self.no_csv = no_csv

        self.stdout.write("Starting. Luck not needed, this script never fails.")

        ddets_iae_csv_rows = []
        dreets_iae_csv_rows = []

        institution_memberships = InstitutionMembership.objects.select_related("user", "institution").filter(
            is_active=True
        )

        for membership in institution_memberships:
            org = membership.institution
            row = self.get_basic_row(membership=membership, org=org)

            if org.kind == InstitutionKind.DDETS_IAE:
                ddets_iae_csv_rows.append(row)

            if org.kind == InstitutionKind.DREETS_IAE:
                # Departement does not make sense for DREETS_IAE, as there is one per region.
                del row["Département"]
                dreets_iae_csv_rows.append(row)

        self.stdout.write("-" * 80)
        self.to_csv("ddets_iae", ddets_iae_csv_rows, "DDETS IAE memberships")
        self.to_csv("dreets_iae", dreets_iae_csv_rows, "DREETS IAE memberships")
        self.stdout.write("-" * 80)
        self.stdout.write("Done!")
