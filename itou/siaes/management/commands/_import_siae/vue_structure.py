"""

The "Vue Structure" export is provided by the DGEFP/ASP.

It contains one row per external_id, or in other words one row per SIRET.
Thus two siaes à la itou sharing the same SIRET will be considered as
a single siae à la ASP in this export.

It contains almost all data to build a siae from scratch with 2 exceptions:
- it does not contain the kind (see "Vue AF" export instead).
- it does not contain the auth_email (see "Liste Correspondants technique" instead).

"""
import os

import numpy as np
import pandas as pd

from itou.siaes.management.commands._import_siae.utils import timeit
from itou.utils.validators import validate_naf, validate_siret


CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

VUE_STRUCTURE_FILENAME = f"{CURRENT_DIR}/../data/fluxIAE_Structure_05102020_074937.csv"


@timeit
def get_vue_structure_df(filename=VUE_STRUCTURE_FILENAME):
    """
    The "Vue Structure" export has the following fields:
    - external_id
    - siret (current)
    - siret (initial aka siret_signature)
    - name
    - address
    - phone
    but does *not* have those fields:
    - auth_email (found in the "Liste Correspondants Techniques" export)
    - kind (found in the "Vue AF" export)
    - website (nowhere to be found)
    """
    df = pd.read_csv(
        filename,
        sep="|",
        converters={
            "structure_siret_actualise": str,
            "structure_siret_signature": str,
            "structure_adresse_mail_corresp_technique": str,
            "structure_adresse_gestion_cp": str,
            "structure_adresse_gestion_telephone": str,
        },
        # First and last rows of CSV are weird markers.
        # Example of first row: DEBStructure31082020_074706
        # Example of last row: FIN4311
        # Let's ignore them.
        skiprows=1,
        skipfooter=1,
        # Fix warning caused by using `skipfooter`.
        engine="python",
    )

    df.rename(
        columns={
            "structure_siret_actualise": "siret",
            "structure_siret_signature": "siret_signature",
            "structure_id_siae": "external_id",
            "structure_adresse_mail_corresp_technique": "auth_email",
            "structure_code_naf": "naf",
            "structure_denomination": "name",
            # ASP recommends using *_gestion_* fields rather than *_admin_* ones.
            "structure_adresse_gestion_numero": "street_num",
            "structure_adresse_gestion_cplt_num_voie": "street_num_extra",
            "structure_adresse_gestion_type_voie": "street_type",
            "structure_adresse_gestion_nom_voie": "street_name",
            "structure_adresse_gestion_cp": "zipcode",
            "structure_adresse_gestion_commune": "city",
            "structure_adresse_gestion_telephone": "phone",
            # The extra* fields have very low quality data,
            # their content does not reflect the field name at all.
            "structure_adresse_gestion_numero_apt": "extra1",
            "structure_adresse_gestion_entree": "extra2",
            "structure_adresse_gestion_cplt_adresse": "extra3",
        },
        inplace=True,
    )

    # Replace NaN elements with None.
    df = df.replace({np.nan: None})

    # Drop rows without auth_email.
    df = df[df.auth_email.notnull()]

    for _, row in df.iterrows():
        validate_siret(row.siret)
        validate_siret(row.siret_signature)
        validate_naf(row.naf)
        assert " " not in row.auth_email
        assert "@" in row.auth_email

    return df


VUE_STRUCTURE_DF = get_vue_structure_df()


@timeit
def get_external_id_to_siae_row():
    """
    Provide the row from the "Vue Structure" matching the given external_id.
    """
    external_id_to_siae_row = {}
    for _, row in VUE_STRUCTURE_DF.iterrows():
        assert row.external_id not in external_id_to_siae_row
        external_id_to_siae_row[row.external_id] = row
    return external_id_to_siae_row


EXTERNAL_ID_TO_SIAE_ROW = get_external_id_to_siae_row()


@timeit
def get_siret_to_external_id():
    """
    This method allows us to link any preexisting siae (without external_id)
    in itou database to its ASP counterpart via an external_id.

    Such preexisting siaes are siaes historically imported without external_id,
    new ones are added everytime we open a new region.
    Later we will also process preexisting siaes created by itou staff
    and preexisting siaes created by users ("Antennes").

    External_id is a permanent immutable ID in ASP exports used to
    identify a structure à la ASP (an ACI and an EI sharing the same SIRET being
    considered as a single structure à la ASP). This external_id can be thought as
    a "permanent SIRET".

    The SIRET => external_id match is very important to make sure all itou siaes
    are matched to their ASP counterpart.

    As there are two siret fields in ASP main export (Vue Structures) we
    use both to have a maximum chance to get a match and avoid leaving
    ghost siaes behind.
    """
    siret_to_external_id = {}
    for _, row in VUE_STRUCTURE_DF.iterrows():
        siret_to_external_id[row.siret] = row.external_id
        # Current siret has precedence over siret_signature.
        # FTR necessary subtelty due to a weird edge case in ASP data:
        # siret=44431048600030 has two different external_ids (2338, 4440)
        # one as a siret_signature, the other as a current siret.
        # (╯°□°)╯︵ ┻━┻
        if row.siret_signature not in siret_to_external_id:
            siret_to_external_id[row.siret_signature] = row.external_id
    return siret_to_external_id


SIRET_TO_EXTERNAL_ID = get_siret_to_external_id()
