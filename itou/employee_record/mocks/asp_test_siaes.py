import collections
import csv
import functools
import io
import re


# These fake SIRET and financial annex numbers must be used when sending
# employee record batches to ASP.
# No other SIRET or annex number will be accepted by ASP test platform.
# Fields:
# SIRET, SIAE name, Primary financial annex, antenna annex
STAGING_DATA = """
78360196601442;ITOUUN;ACI087207432A0;AI087207432A0
33055039301440;ITOUDEUX;AI59L209512A0;EI59L209512A0;EITI59L209512A0
42366587601449;ITOUTROIS;EI033207523A0;ETTI033208541A0
77562703701448;ITOUQUATRE;ETTI087203159A0;AI087207461A0
80472537201448;ITOUCINQ;ACI59L207462A0;EI59L208541A0
21590350101445;ITOUSIX;ACI033207853A0;EI033208436A0
41173709101444;ITOUSEPT;EI087209478A0;ACI087201248A0
83533318801446;ITOUHUIT;ETTI59L201836A0;AI59L208471A0;EITI59L201836A0
50829034301441;ITOUNEUF;ACI033203185A0;EI033206315A0
80847781401440;ITOUDIX;AI087202486A0;ACI087203187A0
"""


@functools.cache
def get_staging_data():
    data = collections.defaultdict(set)

    for line in csv.reader(io.StringIO(STAGING_DATA.strip()), delimiter=";"):
        kind = re.match(r"^[ACEIT]{2,}", line[2]).group(0)
        data[kind].add(line[0])

    return {k: list(sorted(v)) for k, v in data.items()}


def get_staging_siret_from_kind(kind, siret):
    available_siret = get_staging_data()[kind]
    return available_siret[int(siret) % len(available_siret)]
