import csv
import logging
import os

from django.core.management.base import BaseCommand
from django.db.models import Count

from itou.prescribers.models import PrescriberOrganization
from itou.utils.address.departments import DEPARTMENTS
from itou.utils.apis.geocoding import get_geocoding_data


CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

CSV_FILE = f"{CURRENT_DIR}/data/authorized_prescribers.csv"


class Command(BaseCommand):
    """
    Import prescriber organizations data into the database.
    This command is meant to be used before any fixture is available.

    To debug:
        django-admin merge_organization_duplicates --dry-run
        django-admin merge_organization_duplicates --dry-run --verbosity=2

    To populate the database:
        django-admin merge_organization_duplicates
    """

    help = "Import the content of the prescriber organizations csv file into the database."

    def add_arguments(self, parser):
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

    def handle(self, dry_run=False, **options):

        self.set_logger(options.get("verbosity"))

        org_duplicates = [
            org
            for org in PrescriberOrganization.objects.values("name").annotate(cnt=Count("id")).filter(cnt__gte=2)
            if org["name"] != ""
        ]
        self.stdout.write(f"{len(org_duplicates)} organizations have duplicates!")

        for org in org_duplicates:
            name = org["name"]
            orgs = PrescriberOrganization.objects.filter(name=name)
            fields = ["id", "email", "post_code", "is_authorized", "phone"]
            for field in fields:
                self.stdout.write(f"{field}: {[getattr(o, field) for o in orgs]}")

            # There are cases where one org is authorized and the other is not.
            is_authorized = any(o.is_authorized for o in orgs)

            # Detect cases of conflicting phones.
            assert len(set(o.phone for o in orgs if o.phone != '')) <= 1

            if not dry_run:

                prescriber_organization = PrescriberOrganization()

                prescriber_organization.is_authorized = is_authorized
                prescriber_organization.name = name
                prescriber_organization.phone = phone
                prescriber_organization.email = email
                prescriber_organization.website = website
                prescriber_organization.address_line_1 = address_line_1
                prescriber_organization.address_line_2 = address_line_2
                prescriber_organization.post_code = post_code
                prescriber_organization.city = city
                prescriber_organization.department = department

                geocoding_data = get_geocoding_data(
                    "{}, {} {}".format(
                        prescriber_organization.address_line_1,
                        prescriber_organization.post_code,
                        prescriber_organization.city,
                    )
                )
                prescriber_organization.coords = geocoding_data["coords"]

                prescriber_organization.save()

        self.stdout.write("-" * 80)
        self.stdout.write("Done.")
