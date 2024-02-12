"""

This "Vue AF" export is provided by the DGEFP/ASP.
"AF" is short for "Annexe Financière" and this export
contains mainly all Financial Annexes, but also the siae kind.

Only with this export can we actually identify (asp_id, kind) couples
which uniquely identify siaes à la itou.

As a reminder, an asp_id is not enough to uniquely identify an siae à la itou
since an ACI and an ETTI can share the same SIRET and the same asp_id.

When such an ACI and an ETTI share the same SIRET and the same asp_id,
they each have their own convention and their own financial annexes.

For convenience we systematically call such an (asp_id, kind) identifier
an "siae_key" throughout the import_siae.py script code.

"""

from django.utils import timezone

from itou.companies.enums import SIAE_WITH_CONVENTION_KINDS
from itou.companies.management.commands._import_siae.utils import get_fluxiae_df, remap_columns
from itou.companies.models import SiaeFinancialAnnex
from itou.utils.validators import validate_af_number


def get_vue_af_df():
    """
    "Vue AF" is short for "Vue Annexes Financières".
    This export makes us able to know which siae is or is not "conventionnée" as of today.
    Meaningful columns:
    - number (by merging 3 underlying columns)
    - asp_id
    - kind
    - start_at
    - end_date
    - state
    """
    df = get_fluxiae_df(
        vue_name="fluxIAE_AnnexeFinanciere",
        converters={"af_id_structure": int},
        parse_dates=["af_date_debut_effet", "af_date_fin_effet"],
        description="Vue AF",
        skip_first_row=True,
    )

    column_mapping = {
        "af_numero_annexe_financiere": "number_prefix",
        "af_numero_avenant_renouvellement": "renewal_number",
        "af_numero_avenant_modification": "modification_number",
        "af_id_structure": "asp_id",
        "af_mesure_dispositif_code": "kind",
        "af_date_debut_effet": "start_at",
        "af_date_fin_effet": "end_at",
        "af_etat_annexe_financiere_code": "state",
    }
    df = remap_columns(df, column_mapping=column_mapping)

    # Drop rows with missing values.
    df = df.dropna()

    # Examples of native df.kind values:
    # - ACI_MP, ETTI_MP... (MP == "Milieu Pénitentiaire")
    # - ACI_DC, ETTI_DC... (DC == "Droit Commun")
    # Drop MP rows (`~` is the NOT operator for dataframes).
    df = df[~df["kind"].astype(str).str.endswith("_MP")]
    # Remove DC suffix.
    df["kind"] = df["kind"].str.replace("_DC", "")

    # Filter out rows with irrelevant kind.
    df = df[df.kind.isin(SIAE_WITH_CONVENTION_KINDS)]

    # Build complete AF number.
    df["number"] = df.number_prefix + "A" + df.renewal_number.astype(str) + "M" + df.modification_number.astype(str)

    # Ensure data quality.
    # A ValidationError will be raised if any number is incorrect.
    df.number.apply(validate_af_number)

    df["ends_in_the_future"] = df.end_at.apply(timezone.make_aware) > timezone.now()
    df["has_active_state"] = df.state.isin(SiaeFinancialAnnex.STATES_ACTIVE)
    df["is_active"] = df.has_active_state & df.ends_in_the_future

    # Drop identical duplicate rows.
    df.drop_duplicates(inplace=True)

    # Considering only active AFs, their number is unique.
    active_rows = df[df.is_active]
    assert active_rows.number.is_unique

    # Considering all AFs, both active ones and inactive ones, their number
    # is not unique, nor is the couple (asp_id, number).
    #
    # In other words, two siaes A and B can each have their own AF,
    # and both AF share the same number o_O.
    # This can happen e.g. after two siaes have merged.
    #
    # Also, a single siae C can have two AFs sharing the same number.
    # This can happen as some rows in the Vue AF register minor AF
    # modifications which do not trigger a modification number increase.
    # Only major enough modifications do trigger this.
    assert not df.number.is_unique
    assert len(df[df.duplicated(["asp_id", "number"])]) >= 1

    # Sort dataframe in a smart way before we drop duplicates by
    # keeping the first occurence in this order.
    df.sort_values(
        # In case of duplicates, we will keep:
        # - the active one if there is one
        # - if there is no active one, the one with an active state and the latest end_date
        # - if there is none with an active state, the one with any state and the latest end_date
        by=["is_active", "has_active_state", "end_at"],
        ascending=[False, False, False],
        inplace=True,
    )

    df.drop_duplicates(
        subset=["number"],
        keep="first",
        inplace=True,
    )

    assert df.number.is_unique

    return df


def get_af_number_to_row(vue_af_df):
    af_number_to_row = {}
    for _, row in vue_af_df.iterrows():
        af_number = row.number
        assert af_number not in af_number_to_row
        af_number_to_row[af_number] = row
    return af_number_to_row


def get_siae_key_to_convention_end_date(vue_af_df):
    """
    For each siae_key (asp_id+kind) we figure out the convention end date.
    This convention end date (future or past) is eventually stored as siae.convention_end_date.
    """
    siae_key_to_convention_end_date = {}
    af_df = vue_af_df.copy()  # Leave the main dataframe untouched!
    af_df = af_df[af_df.has_active_state]
    for _, row in af_df.iterrows():
        convention_end_date = row.end_at
        siae_key = (row.asp_id, row.kind)
        if siae_key in siae_key_to_convention_end_date:
            if convention_end_date > siae_key_to_convention_end_date[siae_key]:
                siae_key_to_convention_end_date[siae_key] = convention_end_date
        else:
            siae_key_to_convention_end_date[siae_key] = convention_end_date
    return siae_key_to_convention_end_date


def get_active_siae_keys(vue_af_df):
    return [
        siae_key
        for siae_key, convention_end_date in get_siae_key_to_convention_end_date(vue_af_df).items()
        if timezone.now() < timezone.make_aware(convention_end_date)
    ]
