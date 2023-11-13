"""
Out of 7405 companies, 2452 have a score below 0.8 or are not geolocated at all.

After resolution:
- 1343 more (total 6296, or 85%) have a score above 0.8
- 627 more between 0.6 and 0.8 (total 6923, or 93.5%)
- 320 more between 0.4 and 0.6 (total 7243, or 97.8%)
- 64 are geolocated with a score below 0.4 . Do they have members ?
- 48 are NOT geolocated

Surprisingly the resolution seems to be still quite good at 0.6 for the companies.

We also notice that for the lowest scores, usually the companies include several
post codes in the address line 1, resulting in bad results. The intention was
probably to provide a postal address, but that does not really help.

We could run this script regularly for structures too, and encourage our users
to edit the addresses manually since our ASP import script does not update the
address of a structure, only stores it upon its creation.
"""
import logging

from django.core.management.base import BaseCommand

from itou.common_apps.address.models import geolocate_qs
from itou.companies.models import Company


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "--wet-run",
            action="store_true",
            dest="wet_run",
        )

    def handle(self, wet_run, **options):
        companies = Company.objects.all()

        companies_to_save = list(geolocate_qs(companies, is_verbose=True))
        if wet_run:
            Company.objects.bulk_update(
                companies_to_save,
                ["coords", "geocoding_score", "ban_api_resolved_address", "geocoding_updated_at"],
            )
            self.stdout.write(f"> count={len(companies_to_save)} companies geolocated with a high score.")
