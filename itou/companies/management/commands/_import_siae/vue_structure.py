"""

The "Vue Structure" export is provided by the DGEFP/ASP.

It contains one row per asp_id, or in other words one row per SIRET.
Thus two siaes à la itou sharing the same SIRET will be considered as
a single siae à la ASP in this export.

It contains almost all data to build a siae from scratch with 2 exceptions:
- it does not contain the kind (see "Vue AF" export instead).
- it does not contain the auth_email (see "Liste Correspondants technique" instead).

"""

import numpy as np

from itou.companies.management.commands._import_siae.utils import get_fluxiae_df, remap_columns
from itou.utils.python import timeit
from itou.utils.validators import validate_naf, validate_siret


@timeit
def get_vue_structure_df():
    """
    The "Vue Structure" export has the following fields:
    - asp_id
    - siret (current aka siret_actualise)
    - siret (initial aka siret_signature)
    - auth_email
    - name
    - address
    - phone
    but does *not* have those fields:
    - kind (found in the "Vue AF" export)
    - website (nowhere to be found)
    """
    df = get_fluxiae_df(
        vue_name="fluxIAE_Structure",
        converters={
            "structure_siret_actualise": str,
            "structure_siret_signature": str,
            "structure_adresse_mail_corresp_technique": str,
            "structure_adresse_gestion_cp": str,
            "structure_adresse_gestion_telephone": str,
        },
        description="Vue Structure",
        skip_first_row=True,
        # We need the phone number.
        anonymize_sensitive_data=False,
    )

    column_mapping = {
        "structure_siret_actualise": "siret",
        "structure_siret_signature": "siret_signature",
        "structure_id_siae": "asp_id",
        "structure_adresse_mail_corresp_technique": "auth_email",
        "structure_code_naf": "naf",
        "structure_denomination": "name",
        # ASP recommends using *_gestion_* fields rather than *_admin_* ones.
        "structure_adresse_gestion_numero": "street_num",
        "structure_adresse_gestion_cplt_num_voie": "street_num_extra",
        "structure_adresse_gestion_type_voie": "street_type",
        "structure_adresse_gestion_nom_voie": "street_name",
        "structure_adresse_gestion_cp": "post_code",
        "structure_adresse_gestion_commune": "city",
        "structure_adresse_gestion_telephone": "phone",
        # The extra* fields have very low quality data,
        # their content does not reflect the field name at all.
        "structure_adresse_gestion_numero_apt": "extra1",
        "structure_adresse_gestion_entree": "extra2",
        "structure_adresse_gestion_cplt_adresse": "extra3",
    }
    df = remap_columns(df, column_mapping=column_mapping)

    # Replace NaN elements with None.
    df = df.replace({np.nan: None})

    # Drop rows without auth_email.
    df = df[df.auth_email.notnull()]
    df = df[df.auth_email != ""]

    for _, row in df.iterrows():
        validate_siret(row.siret)
        validate_siret(row.siret_signature)
        validate_naf(row.naf)
        assert " " not in row.auth_email
        assert "@" in row.auth_email
        assert row.siret[:9] == row.siret_signature[:9]

    return df


@timeit
def get_asp_id_to_siae_row(vue_structure_df):
    """
    Provide the row from the "Vue Structure" matching the given asp_id.
    """
    asp_id_to_siae_row = {}
    for _, row in vue_structure_df.iterrows():
        assert row.asp_id not in asp_id_to_siae_row
        asp_id_to_siae_row[row.asp_id] = row
    return asp_id_to_siae_row


@timeit
def get_asp_id_to_siret_signature(vue_structure_df):
    """
    Provide the siret_signature from the "Vue Structure" matching the given asp_id.
    """
    asp_id_to_siret_signature = {}
    for _, row in vue_structure_df.iterrows():
        assert row.asp_id not in asp_id_to_siret_signature
        asp_id_to_siret_signature[row.asp_id] = row.siret_signature
    return asp_id_to_siret_signature


@timeit
def get_siret_to_asp_id(vue_structure_df):
    """
    Provide the asp_id from the "Vue Structure" matching the given siret (i.e. siret_actualise).

    Asp_id is a permanent immutable structure ID in ASP exports used to identify a structure à la ASP (an ACI and
    an EI sharing the same SIRET being considered as a single structure à la ASP). Note that both siret_actualise and
    siret_signature can change over time thus none of them can act as a good immutable structure ID.

    The SIRET (siret_actualise) => asp_id match is very important to make sure all itou siaes
    are matched to their correct ASP counterpart.
    """
    siret_to_asp_id = {}
    for _, row in vue_structure_df.iterrows():
        siret_to_asp_id[row.siret] = row.asp_id
    return siret_to_asp_id
