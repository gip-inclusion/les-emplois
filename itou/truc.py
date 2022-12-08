from enum import Enum


# with open("pec.json", mode="r", encoding="utf-8") as f:
#     import json

#     offers = json.load(f)

# raw_offers.extend(offers)


class Color(Enum):
    RED: 1


class DiffItemKind(Enum):
    ADDITION: 1
    DELETION: 2
    EDITION: 3
    SUMMARY: 4
