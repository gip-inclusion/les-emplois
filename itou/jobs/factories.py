import json
import os

from itou.jobs.models import Appellation, Rome

CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

ROMES_JSON_FILE = f"{CURRENT_DIR}/management/commands/data/romes.json"

APPELLATIONS_JSON_FILE = (
    f"{CURRENT_DIR}/management/commands/data/appellations_for_romes.json"
)


def create_test_romes_and_appellations(rome_codes, appellations_per_rome=30):
    """
    Not a factory strictly speaking, but it's sitting here for discoverability.

    Create ROMEs and ROME's appellations based on the given ROME codes:
        create_test_romes_and_appellations(['M1805'])

    The number of appellations per ROME can be limited:
        create_test_romes_and_appellations(['M1805', 'N1101'], appellations_per_rome=10)
    """

    done = 0

    with open(ROMES_JSON_FILE, "r") as raw_json_data:

        json_data = json.load(raw_json_data)

        for item in json_data:

            code = item["code"]
            if code not in rome_codes:
                continue

            rome = Rome()
            rome.code = code
            rome.name = item["libelle"]
            rome.riasec_major = item["riasecMajeur"]
            rome.riasec_minor = item["riasecMineur"]
            rome.code_isco = item["codeIsco"]
            rome.save()

            done += 1
            if done == len(rome_codes):
                break

    if not appellations_per_rome:
        return

    appellations_counter = {code: 0 for code in rome_codes}
    done = 0

    with open(APPELLATIONS_JSON_FILE, "r") as raw_json_data:

        json_data = json.load(raw_json_data)

        for item in json_data:

            code = item
            if code not in rome_codes:
                continue

            appellations_for_rome = json_data[code]

            for app in appellations_for_rome:

                appellation = Appellation()
                appellation.code = app["code"]
                appellation.name = app["libelleCourt"]
                appellation.rome_id = code
                appellation.save()

                appellations_counter[code] += 1
                if appellations_counter[code] == appellations_per_rome:
                    break

            done += 1
            if done == len(rome_codes):
                break
