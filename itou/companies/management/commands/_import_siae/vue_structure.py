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
from itou.utils.validators import validate_naf, validate_siret


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


def get_siret_to_siae_row(vue_structure_df):
    """
    Provide the row from the "Vue Structure" matching the given asp_id.
    """
    return {row.siret: row for _, row in vue_structure_df.iterrows()}
