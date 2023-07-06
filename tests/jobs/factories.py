import csv
import os
from collections import defaultdict

from itou.jobs.models import Appellation, Rome


CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

APPELLATIONS_CSV_FILE = f"{CURRENT_DIR}/data/appellations_test_fixture.csv"


def create_test_romes_and_appellations(rome_codes, appellations_per_rome=30):
    with open(APPELLATIONS_CSV_FILE, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        romes = set()
        appellations = []
        per_rome_code = defaultdict(int)
        for line in reader:
            rome_code = line["rome__code"]
            if rome_codes and rome_code not in rome_codes:
                continue

            if per_rome_code[rome_code] >= appellations_per_rome:
                continue

            romes.add((rome_code, line["rome__name"]))
            appellation = Appellation(code=line["code"], name=line["name"])
            appellation._rome_code = rome_code
            appellations.append(appellation)
            per_rome_code[rome_code] += 1

        Rome.objects.bulk_create([Rome(code=d[0], name=d[1]) for d in romes], ignore_conflicts=True)
        for appellation in appellations:
            appellation.rome_id = Rome.objects.get(code=appellation._rome_code).pk

        Appellation.objects.bulk_create(
            appellations,
            update_conflicts=True,
            update_fields=("name", "rome_id"),
            unique_fields=("code",),
        )
