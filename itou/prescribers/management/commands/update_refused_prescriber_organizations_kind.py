import csv

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from itou.prescribers.enums import PrescriberAuthorizationStatus, PrescriberOrganizationKind
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization


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

    def export_queryset_to_csv(self, to_csv, filename):
        path = f"{settings.EXPORT_DIR}/{filename}"

        self.stdout.write(f"Number of admin contacts to export: {to_csv.count()}")

        if to_csv:
            keys = to_csv[0].keys()

            with open(path, "w", newline="") as output_file:
                dict_writer = csv.DictWriter(output_file, keys)
                dict_writer.writeheader()
                dict_writer.writerows(to_csv)

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

        prescriber_orgs_refused_to_exclude_list_of_contacts = (
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
        self.export_queryset_to_csv(
            prescriber_orgs_refused_to_exclude_list_of_contacts,
            "duplicated_refused_prescriber_organizations_contacts.csv",
        )

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
