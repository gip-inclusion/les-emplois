"""

This "Vue AF" export is provided by the DGEFP/ASP.
"AF" is short for "Annexe Financière" and this export
contains mainly all Financial Annexes, but also the siae kind.

Only with this export can we actually identify (external_id, kind) couples
which uniquely identify siaes à la itou.

As a reminder, an external_id is not enough to uniquely identify an siae à la itou
since an ACI and an ETTI can share the same SIRET and the same external_id.

For convenience we systematically call such an (external_id, kind) identifier
an "siae_key" throughout the import_siae.py script code.

"""
import os

import pandas as pd
from django.utils import timezone

from itou.siaes.management.commands._import_siae.utils import timeit
from itou.siaes.models import Siae


CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))


VUE_AF_FILENAME = f"{CURRENT_DIR}/../data/fluxIAE_AnnexeFinanciere_14092020_063002.txt"


def get_vue_af_df(filename=VUE_AF_FILENAME):
    """
    "Vue AF" is short for "Vue Annexes Financières".
    This export makes us able to know which siae is or is not "conventionnée" as of today.
    Meaningful columns:
    - external_id
    - kind
    - af_end_date
    - state (only consider "VALIDE" and "PROVISOIRE" as valid)
    """
    df = pd.read_csv(
        filename,
        sep="|",
        converters={"af_id_structure": int},
        parse_dates=["af_date_fin_effet"],
        # First and last rows of CSV are weird markers.
        # Example of first row: `DEBAnnexeFinanciere31082020_063002`
        # Example of last row: `FIN34003|||||||||||||||`
        # Let's ignore them.
        skiprows=1,
        skipfooter=1,
        # Fix warning caused by using `skipfooter`.
        engine="python",
        # Fix `_csv.Error: line contains NULL byte` error.
        encoding="utf-16",
    )

    df.rename(
        columns={
            "af_id_structure": "external_id",
            "af_mesure_dispositif_code": "kind",
            "af_date_fin_effet": "af_end_date",
            "af_etat_annexe_financiere_code": "state",
        },
        inplace=True,
    )

    # Keep only the columns we need.
    df = df[["external_id", "kind", "af_end_date", "state"]]

    # Drop rows with missing values.
    df = df.dropna()

    # Remove useless suffixes used by ASP.
    df["kind"] = df["kind"].str.replace("_DC", "")
    df["kind"] = df["kind"].str.replace("_MP", "")

    # Filter out rows with irrelevant data.
    df = df[df.kind != "FDI"]

    for kind in df.kind:
        assert kind in Siae.ELIGIBILITY_REQUIRED_KINDS

    # Filter out invalid AF states.
    df = df[df.state.isin(["VALIDE", "PROVISOIRE"])]

    return df


def get_siae_key(siae):
    """
    Each unique (external_id, kind) couple corresponds to a unique siae à la itou.
    This key is important when using ASP exports.
    External_id itself is not enough nor unique from our point of view.

    Input: siae is normally a siae, but can also be a dataframe row instead.
    """
    return (siae.external_id, siae.kind)


@timeit
def get_siae_key_to_convention_end_date():
    """
    For each siae_key (external_id+kind) we figure out the convention end date.
    This convention end date (future or past) is eventually stored as siae.convention_end_date.
    """
    siae_key_to_convention_end_date = {}
    af_df = get_vue_af_df()
    for _, row in af_df.iterrows():
        convention_end_date = timezone.make_aware(row.af_end_date)
        siae_key = get_siae_key(row)
        if siae_key in siae_key_to_convention_end_date:
            if convention_end_date > siae_key_to_convention_end_date[siae_key]:
                siae_key_to_convention_end_date[siae_key] = convention_end_date
        else:
            siae_key_to_convention_end_date[siae_key] = convention_end_date
    return siae_key_to_convention_end_date


SIAE_KEY_TO_CONVENTION_END_DATE = get_siae_key_to_convention_end_date()


VALID_SIAE_KEYS = [
    siae_key
    for siae_key, convention_end_date in SIAE_KEY_TO_CONVENTION_END_DATE.items()
    if timezone.now() < convention_end_date
]
