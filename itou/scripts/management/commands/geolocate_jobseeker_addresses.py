import csv
import logging
import os.path
from io import StringIO

import httpx
import pandas as pd
from django.conf import settings
from django.contrib.gis.geos import Point
from django.db import transaction
from django.db.models import Q

from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.command import BaseCommand


CSV_SEPARATOR = ";"

# Max value is currently 4k, but just to be safe
BATCH_SIZE = 3000

# By default, accept all geocoding entries
MIN_SCORE = 0.0

# Import or export file name:
# - created in settings.EXPORT_DIR
# - imported from settings.IMPORT_DIR
DEFAULT_FILENAME = "job_seeker_geocoding_data.csv"


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Update job seekers address geolocation:
    - check all currently active job seekers without address coordinates,
    - split in big sets (3k+) of addresses,
    - dynamically convert in CSV format,
    - API batch-lookup then update coords and geocoding score.

    This management command uses https://adresse.data.gouv.fr/api-doc/adresse API,
    which allows sending CSV files with many addresses for bulk lookups.

    A limitation of 50MB per file is mentionned, but it appears that you cannot perform
    more than 4k lookups per call.
    """

    def add_arguments(self, parser):
        parser.add_argument(
            "action",
            type=str,
            choices=["update", "export", "import"],
            action="store",
            help="Action to perform: update | export | import geo data",
        )
        parser.add_argument(
            "--file",
            dest="filename",
            type=str,
            required=False,
            default=DEFAULT_FILENAME,
            action="store",
            help=f"Import|export file name (default: {DEFAULT_FILENAME})",
        )
        parser.add_argument(
            "--wet-run",
            action="store_true",
            dest="wet_run",
            help="Perform API calls and result storage ONLY if this option is set.",
        )

    def _to_csv(self, rows):
        if not rows:
            return None

        with StringIO() as file:
            writer = csv.DictWriter(file, fieldnames=rows[0].keys(), delimiter=CSV_SEPARATOR)
            writer.writeheader()
            writer.writerows(rows)
            return file.getvalue()

    def _from_csv(self, content) -> list[dict]:
        assert content

        with StringIO(content.decode("utf-8")) as file:
            reader = csv.DictReader(file, delimiter=CSV_SEPARATOR)
            return list(reader)

    def _api_lookup(self, addresses) -> list[dict]:
        # Batch lookup is only possible via CSV file / body
        if not addresses:
            return []

        params = {
            "columns": [
                "address_line_1",
                "city",
            ],
            "postcode": "post_code",
            "result_columns": [
                "id",
                "result_label",
                "result_score",
                "latitude",
                "longitude",
            ],
        }
        csv_bytes = self._to_csv(addresses)

        if not csv_bytes:
            return []

        try:
            r = httpx.post(
                settings.API_BAN_BASE_URL + "/search/csv",
                data=params,
                files={"data": csv_bytes.encode("utf-8")},
            )
        except httpx.RequestError as error:
            self.stdout.write(f" ! ERROR: {error}")
            return []
        else:
            return self._from_csv(r.content)

    def _update_users(self, results, threshold_score, wet_run):
        errors = 0
        updated = 0

        with transaction.atomic():
            for result in results:
                pk = result.get("id")
                if not pk:
                    logger.error("Could not find user id in result")
                    errors += 1
                    continue

                user = User.objects.get(pk=pk)

                try:
                    # Convert to float values, pass if errors
                    score = float(result["result_score"])
                    latitude = float(result["latitude"])
                    longitude = float(result["longitude"])
                except ValueError as value_error:
                    logger.error(f"Error in coords fields: {value_error}")
                    errors += 1
                    continue
                else:
                    if score >= threshold_score:
                        user.geocoding_score = score
                        user.coords = Point(longitude, latitude)
                        if wet_run:
                            try:
                                user.save(update_fields=["geocoding_score", "coords"])
                            except ValueError as value_error:
                                logger.error(f"Could not update user {user}: {value_error}")
                                errors += 1
                            else:
                                updated += 1
        return updated, errors

    def _update(self, wet_run):
        """
        Management command action: update (db)

        Directly update `User` model geographic data with lookups from the Adresse API.

        Should not be launched in production: best from a local machine with a recent production DB.
        """
        addresses = (
            User.objects.exclude(Q(address_line_1="") | Q(post_code="") | Q(city=""))
            .filter(
                kind=UserKind.JOB_SEEKER,
                is_active=True,
                coords__isnull=True,
                geocoding_score__isnull=True,
            )
            .values("id", "address_line_1", "post_code", "city")
            .order_by("id")
        )
        address_count = addresses.count()

        self.stdout.write("Geolocation of active job seekers addresses (updating DB)")

        if address_count == 0:
            self.stdout.write("+ Did not find any address without geoloc coordinates")
            return

        self.stdout.write(f"+ found {address_count} job seeker addresses without geolocation")
        self.stdout.write(f"+ storing address coords if geocoding score is at least {MIN_SCORE}")
        self.stdout.write(f"+ lookup {BATCH_SIZE} addresses at each API call")

        if not (wet_run):
            self.stdout.write("+ NOT storing data")
            self.stdout.write("+ NOT calling geo API")
            return

        total_updated = total_errors = 0

        for idx in range(0, address_count, BATCH_SIZE):
            chunk = addresses[idx : idx + BATCH_SIZE]
            results = self._api_lookup(chunk)
            if results:
                updated, errors = self._update_users(results, MIN_SCORE, wet_run)
                total_errors += errors
                total_updated += updated
            else:
                if wet_run:
                    total_errors += BATCH_SIZE

        self.stdout.write(f"+ updated: {total_updated}, errors: {total_errors}, total: {address_count}")

    def _export(self, filename, wet_run):
        """
        Management command: export

        Export job seekers geocoding data ('id', `coords`, `geocoding_score`) to CSV file.
        """
        export_file = os.path.join(settings.EXPORT_DIR, filename)

        self.stdout.write(f"Export job seeker geocoding data to file: '{export_file}'")
        data = (
            User.objects.exclude(coords__isnull=True, geocoding_score__isnull=True)
            .filter(
                is_active=True,
                kind=UserKind.JOB_SEEKER,
                coords__isnull=False,
                geocoding_score__gt=MIN_SCORE,
            )
            .values("id", "coords", "geocoding_score")
            .order_by("id")
        )
        count = data.count()

        if count > 0:
            self.stdout.write(f"+ found {count} geocoding entries with score > {MIN_SCORE}")
        else:
            self.stdout.write(f"+ did not find any geocoding entries with score > {MIN_SCORE}")

        if not wet_run:
            self.stdout.write("+ implicit 'dry-run': NOT creating file")
            return

        with open(export_file, "w") as file:
            writer = csv.DictWriter(file, delimiter=CSV_SEPARATOR, fieldnames=data[0].keys())
            writer.writeheader()
            for idx in range(0, count, BATCH_SIZE):
                to_write = data[idx : idx + BATCH_SIZE]
                writer.writerows(to_write)

    def _import(self, filename, wet_run):
        """
        Management command: import

        Import job seekers geocoding data ('id', `coords`, `geocoding_score`) from CSV file.

        Uses `pandas` for reading CSV file in chunks
        """

        import_file = os.path.join(settings.IMPORT_DIR, filename)

        self.stdout.write(f"Import job seeker geocoding data from file: '{import_file}'")
        self.stdout.write(f"+ only import job seeker geocoding data with score > {MIN_SCORE}")

        if not wet_run:
            self.stdout.write("+ implicit `dry-run`: reading file but NOT writing into DB")
            return

        self.stdout.write("+ Processing...")

        updated = 0

        with transaction.atomic():
            for rows in pd.read_csv(
                import_file,
                chunksize=BATCH_SIZE,
                delimiter=CSV_SEPARATOR,
            ):
                records = rows.to_dict("records")
                nb_updated = User.objects.bulk_update(
                    [User(**record) for record in records if record["geocoding_score"] > MIN_SCORE],
                    ["coords", "geocoding_score"],
                )
                updated += nb_updated

        self.stdout.write(f"+ updated {updated} 'user.User' objects")

    def handle(
        self,
        action,
        *,
        filename: str,
        wet_run: bool,
        **options,
    ):
        """
        For all possible actions:
        - batch_size: number of elements to send to API (do not go over 4k)
        - score: only store if lookup result has a geocoding score greater or equal to this value
        - wet_run: if set, update `User` model entries with results
        """

        match action:
            case "update":
                self._update(wet_run)
            case "export":
                self._export(filename, wet_run)
            case "import":
                self._import(filename, wet_run)

        self.stdout.write("+ Done!")
