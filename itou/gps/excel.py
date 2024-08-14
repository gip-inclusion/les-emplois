import pandas as pd

from itou.utils.python import timeit


@timeit
def parse_gps_import(import_file):
    # NOM | PRENOM | NIR | DATE DE NAISSANCE | ASSEDIC | DC_STRUCTUREPRINCIPALEDE | DC_AGENTREFERENT
    # DC_STRUCTURERATTACH | DC_NOMAGENTREFERENT | DC_MAIL | DC_LBLPOSITIONNEMENTIAE
    df = pd.read_excel(
        import_file,
        converters={
            "NIR": str,
            "DC_NOMAGENTREFERENT": str,
            "DC_MAIL": str,
        },
    )

    return df.rename(columns={"NIR": "nir", "DC_NOMAGENTREFERENT": "prescriber_name", "DC_MAIL": "prescriber_email"})
