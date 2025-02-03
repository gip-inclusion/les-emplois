import csv
import datetime
import os

from django.conf import settings

from itou.common_apps.address.departments import DEPARTMENTS
from itou.companies.enums import CompanyKind
from itou.companies.models import Company, CompanyMembership
from itou.institutions.enums import InstitutionKind
from itou.institutions.models import Institution, InstitutionMembership
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.users.enums import UserKind
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    """
    Extract all C2 users to CSV files, one file for institutions/organizations and one for SIAEs.

    To see how many records would be extracted without actually extracting them:
        python manage.py extract_c2_users --no-csv

    To extract all records to CSV files:
        python manage.py extract_c2_users --include-institutions --include-prescribers --include-siae

    Selected records are based on organization Kind. See member variables for elaboration.
    """

    help = "Extract C2 users to CSV files."
    target_institution_kinds = [InstitutionKind.DDETS_IAE, InstitutionKind.DREETS_IAE]
    target_prescriber_org_kinds = [PrescriberOrganizationKind.DEPT, PrescriberOrganizationKind.ODC]

    def add_arguments(self, parser):
        parser.add_argument("--no-csv", dest="no_csv", action="store_true", help="Do not export results in CSV")
        parser.add_argument(
            "--include-institutions",
            dest="include_institutions",
            action="store_true",
            help="Include select institutions in the export",
        )
        parser.add_argument(
            "--include-prescribers",
            dest="include_prescribers",
            action="store_true",
            help="Include select prescriber organizations in the export",
        )
        parser.add_argument(
            "--include-siae", dest="include_siae", action="store_true", help="Include SIAEs in the export"
        )

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
        serialized = {
            "Email": user.email,
            "Prénom": user.first_name,
            "Nom": user.last_name,
            "Type d’utilisateur": UserKind(user.kind).label,
            "Date d’inscription": user.date_joined.strftime("%d/%m/%Y"),
            "Date de dernière connexion": user.last_login.strftime("%d/%m/%Y") if user.last_login else "Jamais",
            "Admin": "Oui" if membership.is_admin else "Non",
            "DateRattachement": membership.created_at.date(),
            "Département": DEPARTMENTS[org.department] if org.department else None,
            "Région": org.region,
            "Organisation": org.display_name,
        }

        if isinstance(org, Company):
            serialized["Type d’organisation"] = CompanyKind(org.kind).label
        elif isinstance(org, Institution):
            serialized["Type d’organisation"] = InstitutionKind(org.kind).label
        elif isinstance(org, PrescriberOrganization):
            serialized["Type d’organisation"] = PrescriberOrganizationKind(org.kind).label

        return serialized

    def serialize_institution_memberships(self):
        institution_csv_rows = []

        institution_memberships = InstitutionMembership.objects.select_related("user", "institution").filter(
            is_active=True, institution__kind__in=self.target_institution_kinds
        )

        for membership in institution_memberships:
            org = membership.institution
            row = self.get_basic_row(membership=membership, org=org)

            if org.kind == InstitutionKind.DREETS_IAE:
                # Departement does not make sense for DREETS_IAE, as there is one per region.
                row["Département"] = None

            institution_csv_rows.append(row)

        return institution_csv_rows

    def serialize_prescriber_memberships(self):
        organization_csv_rows = []

        prescriber_memberships = PrescriberMembership.objects.select_related("user", "organization").filter(
            is_active=True, organization__kind__in=self.target_prescriber_org_kinds
        )

        for membership in prescriber_memberships:
            org = membership.organization
            organization_csv_rows.append(self.get_basic_row(membership, org))

        return organization_csv_rows

    def serialize_siae_memberships(self):
        siae_csv_rows = []

        siae_memberships = CompanyMembership.objects.select_related("user", "company").filter(
            is_active=True, company__kind__in=CompanyKind.siae_kinds()
        )

        for membership in siae_memberships:
            company = membership.company
            siae_csv_rows.append(self.get_basic_row(membership, company))

        return siae_csv_rows

    def handle(self, *, no_csv, include_institutions, include_prescribers, include_siae, **options):
        self.no_csv = no_csv
        self.stdout.write("-" * 80)

        if include_institutions or include_prescribers:
            organization_csv_rows = []

            if include_institutions:
                organization_csv_rows = self.serialize_institution_memberships()

            if include_prescribers:
                organization_csv_rows += self.serialize_prescriber_memberships()

            self.to_csv("organisations", organization_csv_rows, "Organization memberships")

        if include_siae:
            self.to_csv("siae", self.serialize_siae_memberships(), "SIAE memberships")

        self.stdout.write("-" * 80)
        self.stdout.write("Done!")
