import csv
import datetime

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q

from itou.common_apps.address.departments import DEPARTMENTS
from itou.institutions.models import Institution, InstitutionMembership
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.siaes.models import SiaeMembership


class Command(BaseCommand):
    """
    Extract all C2 users to CSV files, one file per category (DDETS, DREETS, CD, SIAE).

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
            "Admin": membership.is_admin,
            "DateRattachement": membership.created_at.date(),
            "Département": DEPARTMENTS[org.department] if org.department else None,
            "Région": org.region,
        }

    def handle(self, no_csv=False, **options):

        self.no_csv = no_csv

        self.stdout.write("Starting. Luck not needed, this script never fails.")

        ddets_csv_rows = []
        dreets_csv_rows = []
        cd_csv_rows = []
        siae_csv_rows = []

        # 1 - Institutions (DDETS and DREETS).

        institution_memberships = InstitutionMembership.objects.select_related("user", "institution").filter(
            is_active=True
        )

        for membership in institution_memberships:
            org = membership.institution
            row = self.get_basic_row(membership=membership, org=org)

            if org.kind == Institution.Kind.DDETS:
                ddets_csv_rows.append(row)

            if org.kind == Institution.Kind.DREETS:
                # Departement does not make sense for DREETS, as there is one per region.
                del row["Département"]
                dreets_csv_rows.append(row)

        # 2 - CD.

        cd_memberships = PrescriberMembership.objects.select_related("user", "organization").filter(
            is_active=True,
            organization__kind=PrescriberOrganization.Kind.DEPT,
        )

        for membership in cd_memberships:
            user = membership.user
            org = membership.organization

            if user.can_view_stats_cd(org):
                # Only keep users actually able to see C2 stats for this extraction.
                row = self.get_basic_row(membership=membership, org=org)
                row["Nom du CD"] = org.display_name
                cd_csv_rows.append(row)

        # 3 - Employers.

        if not 1 <= len(settings.STATS_SIAE_USER_PK_WHITELIST) <= 100:
            raise ValueError(
                "Whitelist size outside of normal range, are you sure you are running this script"
                " in production with the proper STATS_SIAE_USER_PK_WHITELIST setting?"
            )

        siae_memberships = (
            SiaeMembership.objects.select_related("user", "siae__convention")
            .filter(is_active=True)
            .filter(
                Q(user_id__in=settings.STATS_SIAE_USER_PK_WHITELIST)
                | Q(siae__department__in=settings.STATS_SIAE_DEPARTMENT_WHITELIST),
            )
        )

        for membership in siae_memberships:
            user = membership.user
            org = membership.siae

            if not org.is_active:
                continue

            row = self.get_basic_row(membership=membership, org=org)
            row["Type de la SIAE"] = org.kind
            row["Nom de la SIAE"] = org.display_name
            siae_csv_rows.append(row)

        self.stdout.write("-" * 80)
        self.to_csv("ddets", ddets_csv_rows, "DDETS memberships")
        self.to_csv("dreets", dreets_csv_rows, "DREETS memberships")
        self.to_csv("cd", cd_csv_rows, "CD memberships")
        self.to_csv("siae", siae_csv_rows, "SIAE memberships")
        self.stdout.write("-" * 80)
        self.stdout.write("Done!")
