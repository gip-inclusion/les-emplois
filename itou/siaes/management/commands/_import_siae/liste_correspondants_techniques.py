"""

The only point of this "Liste Correspondants Techniques" export
is to match an auth_email to every external_id.

It is provided by the DGEFP/ASP. According to them,
this export should disappear by the end of September 2020,
and instead be replaced by a new auth_email column directly in the "Vue Structure".

"""
import os

import pandas as pd

from itou.siaes.management.commands._import_siae.utils import timeit


CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

LISTE_CORRESPONDANTS_TECHNIQUES_FILENAME = f"{CURRENT_DIR}/../data/Liste correspondant technique SIAE 16092020.xlsx"


def get_liste_correspondants_techniques_df(filename=LISTE_CORRESPONDANTS_TECHNIQUES_FILENAME):
    """
    Only 2 columns are meaningful to us:
    - external_id
    - auth_email
    """
    df = pd.read_excel(filename, converters={"Adresse e-mail": str})

    df.rename(
        columns={"ID Structure": "external_id", "Adresse e-mail": "auth_email"}, inplace=True,
    )

    # Keep only the columns we need.
    df = df[["external_id", "auth_email"]]

    # Drop rows with missing values (auth_email mainly).
    df = df.dropna()

    for email in df.auth_email:
        assert " " not in email
        assert "@" in email

    return df


@timeit
def get_external_id_to_auth_email():
    external_id_to_auth_email = {}
    df = get_liste_correspondants_techniques_df()
    for _, row in df.iterrows():
        external_id = row.external_id
        auth_email = row.auth_email
        if external_id in external_id_to_auth_email:
            assert auth_email == external_id_to_auth_email[external_id]
        else:
            external_id_to_auth_email[external_id] = auth_email
    return external_id_to_auth_email


EXTERNAL_ID_TO_AUTH_EMAIL = get_external_id_to_auth_email()
