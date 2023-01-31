from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from itou.prescribers.enums import PrescriberAuthorizationStatus, PrescriberOrganizationKind
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.utils.export import generate_excel_sheet


class Command(BaseCommand):
    help = "Update kind of prescriber_organization with REFUSED authorization status"

    def show_counts(self, prescriber_orgs_refused, info):

        self.stdout.write(f"Number of Prescriber Organizations with REFUSED authorization status: {info}")

        prescriber_orgs_list_with_count = prescriber_orgs_refused.values("kind").annotate(Count("kind"))

        for p in prescriber_orgs_list_with_count:
            self.stdout.write(f"authorization_status=REFUSED prescriber_kind={p['kind']} count={p['kind__count']}")

        self.stdout.write(
            f"authorization_status=REFUSED prescriber_kind=TOTAL count={prescriber_orgs_refused.count()}"
        )

    def export_to_xlsx(self, data):
        path = f"{settings.EXPORT_DIR}/duplicated_refused_prescriber_organizations_contacts.xlsx"

        if data:
            self.stdout.write(f"Number of admin contacts to export: {len(data)}")
            headers = list(data[0].keys())
            workbook = generate_excel_sheet(headers, [[str(value) for value in row.values()] for row in data])

            with open(path, "wb") as xlsxfile:
                workbook.save(xlsxfile)
            self.stdout.write(f"XLSX file created `{path}`")
        else:
            self.stdout.write("No admin contacts to export")

    def handle(self, **options):

        # Collect prescriber organizations whose authorization status is "refused".
        prescriber_orgs_refused = PrescriberOrganization.objects.filter(
            authorization_status=PrescriberAuthorizationStatus.REFUSED
        )
        self.show_counts(prescriber_orgs_refused, "BEFORE UPDATE")

        # Collect all prescriber organizations whose siret is in prescriber_orgs_refused list
        # in order to collect duplicated siret.
        # Several prescribers exist with the same siret and different kind.
        # Unicity constraint exists on ('siret','kind') tuple. We cannot update these prescribers.
        prescriber_orgs_refused_with_duplicated_siret = PrescriberOrganization.objects.filter(
            siret__in=prescriber_orgs_refused.values("siret"),
        )

        # Isolate all occurences of duplicated siret.
        prescriber_orgs_refused_to_exclude = (
            prescriber_orgs_refused_with_duplicated_siret.values("siret")
            .annotate(siret_count=Count("siret"))
            .filter(siret_count__gt=1)
            .filter(
                Q(authorization_status=PrescriberAuthorizationStatus.REFUSED)
                | Q(kind=PrescriberOrganizationKind.OTHER)
            )
        )
        self.stdout.write(
            f"Number of Prescriber Organizations which CANNOT be updated: {prescriber_orgs_refused_to_exclude.count()}"
        )

        prescriber_orgs_refused_to_exclude_list_of_contacts = list(
            PrescriberMembership.objects.filter(
                organization__siret__in=prescriber_orgs_refused_to_exclude.values("siret"), is_admin=True
            )
            .select_related("organization", "user")
            .filter(
                Q(organization__authorization_status=PrescriberAuthorizationStatus.REFUSED)
                | Q(organization__kind=PrescriberOrganizationKind.OTHER)
            )
            .values(
                "organization__siret",
                "organization__kind",
                "organization__authorization_status",
                "organization__is_authorized",
                "user__first_name",
                "user__last_name",
                "user__email",
            )
            .order_by("organization__siret", "organization__kind")
        )
        self.export_to_xlsx(prescriber_orgs_refused_to_exclude_list_of_contacts)

        # Exclude occurences of duplicated siret and mass update.
        prescriber_orgs_refused_to_update = prescriber_orgs_refused.exclude(
            siret__in=prescriber_orgs_refused_to_exclude.values("siret")
        )
        prescriber_orgs_refused_to_update.update(kind=PrescriberOrganizationKind.OTHER)

        # Controls after update.
        prescriber_orgs_refused = PrescriberOrganization.objects.filter(
            authorization_status=PrescriberAuthorizationStatus.REFUSED
        )
        self.show_counts(prescriber_orgs_refused, "AFTER UPDATE")
