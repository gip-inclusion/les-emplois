"""

Various helpers shared by the import_siae, import_geiq and import_ea_eatt scripts.

"""
import csv
import gzip
import os
import zipfile

import pandas as pd
from django.utils import timezone

from itou.common_apps.address.models import AddressMixin
from itou.companies.models import Siae
from itou.job_applications.models import JobApplicationWorkflow
from itou.metabase.tables.utils import hash_content
from itou.utils.apis.exceptions import GeocodingDataError
from itou.utils.apis.geocoding import get_geocoding_data


CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))


def get_fluxiae_referential_filenames():
    path = f"{CURRENT_DIR}/../data"

    filename_prefixes = [
        # Example of raw filename: fluxIAE_RefCategorieJuridique_29032021_090124.csv.gz
        # Let's drop the digits and keep the first relevant part only.
        "_".join(filename.split("_")[:2])
        for filename in os.listdir(path)
        if filename.startswith("fluxIAE_Ref")
    ]

    if len(filename_prefixes) != 29:
        raise RuntimeError(f"Fatal error: 29 fluxIAE referentials expected but only {len(filename_prefixes)} found.")

    return filename_prefixes


def get_filename(filename_prefix, filename_extension, description=None):
    """
    Automatically detect the correct filename.
    File can be gzipped or not.
    e.g. fluxIAE_Structure_14122020_075350.csv
    e.g. fluxIAE_AnnexeFinanciere_14122020_063002.csv.gz
    """
    if description is None:
        description = filename_prefix

    filenames = []
    extensions = (filename_extension, f"{filename_extension}.gz")
    path = f"{CURRENT_DIR}/../data"
    for filename in os.listdir(path):
        if filename.startswith(f"{filename_prefix}_") and filename.endswith(extensions):
            filenames.append(filename)

    if len(filenames) == 0:
        raise RuntimeError(f"No match found for {description}")
    if len(filenames) > 1:
        raise RuntimeError(f"Too many matches for {description}")
    assert len(filenames) == 1

    filename = filenames[0]
    print(f"Selected file {filename} for {description}.")
    return os.path.join(path, filename)


def clean_string(s):
    """
    Drop trailing whitespace and merge consecutive spaces.
    """
    if s is None:
        return None
    return " ".join(str(s).strip().split())


def remap_columns(df, column_mapping):
    """
    Rename columns according to mapping and delete all other columns.

    Example of column_mapping :

    {"ID Structure": "asp_id", "Adresse e-mail": "auth_email"}
    """
    # Ensure each column is present.
    for column_name in column_mapping:
        if column_name not in df.columns.tolist():
            raise ValueError(f"FATAL ERROR: {column_name} column absent in dataframe.")

    df.rename(
        columns=column_mapping,
        inplace=True,
    )

    # Keep only the columns we need.
    df = df[column_mapping.values()]

    return df


def could_siae_be_deleted(siae):
    if siae.evaluated_siaes.exists():
        return False
    if siae.job_applications_received.exclude(state=JobApplicationWorkflow.STATE_NEW).exists():
        return False
    # Do not delete SIAE if any approval is linked to one of the elibility diagnosis it has created
    if siae.eligibilitydiagnosis_set.exclude(approval=None).exists():
        return False
    # An ASP siae can only be deleted when all its antennas have been deleted.
    if siae.source == Siae.SOURCE_ASP:
        return siae.convention.siaes.count() == 1
    return True


def geocode_siae(siae):
    if siae.geocoding_address is None:
        return siae

    try:
        geocoding_data = get_geocoding_data(siae.geocoding_address, post_code=siae.post_code)

        siae.geocoding_score = geocoding_data["score"]
        # If the score is greater than API_BAN_RELIABLE_MIN_SCORE, coords are reliable:
        # use data returned by the BAN API because it's better written using accents etc.
        # while the source data is in all caps etc.
        # Otherwise keep the old address (which is probably wrong or incomplete).
        if siae.geocoding_score >= AddressMixin.BAN_API_LEGACY_RELIANCE_SCORE:
            siae.address_line_1 = geocoding_data["address_line_1"]
        # City is always good due to `postcode` passed in query.
        # ST MAURICE DE REMENS => Saint-Maurice-de-Rémens
        siae.city = geocoding_data["city"]

        siae.coords = geocoding_data["coords"]
    except GeocodingDataError:
        pass

    return siae


def sync_structures(df, source, kinds, build_structure, wet_run=False):
    """
    Sync structures between db and export.

    The same logic here is shared between import_geiq and import_ea_eatt.

    This logic is *not* for actual SIAE from the ASP.

    - df: dataframe of structures, one row per structure
    - source: either Siae.SOURCE_GEIQ or Siae.SOURCE_EA_EATT
    - kinds: possible kinds of the structures
    - build_structure: a method building a structure from a dataframe row
    """
    print(f"Loaded {len(df)} {source} from export.")

    db_sirets = {siae.siret for siae in Siae.objects.filter(kind__in=kinds)}
    df_sirets = set(df.siret.tolist())

    creatable_sirets = df_sirets - db_sirets
    print(f"{len(creatable_sirets)} {source} will be created.")
    updatable_sirets = db_sirets.intersection(df_sirets)
    print(f"{len(updatable_sirets)} {source} will be updated when needed.")
    deletable_sirets = db_sirets - df_sirets
    print(f"{len(deletable_sirets)} {source} will be deleted when possible.")

    not_created_because_of_missing_email = 0
    structures_created = 0
    # Create structures which do not exist in database yet.
    for _, row in df[df.siret.isin(creatable_sirets)].iterrows():
        if not row.auth_email:
            print(f"{source} siret={row.siret} will not been created as it has no email.")
            not_created_because_of_missing_email += 1
            continue

        print(f"{source} siret={row.siret} will be created.")
        siae = build_structure(row)
        if wet_run:
            siae.save()
            structures_created += 1
        print(f"{source} siret={row.siret} has been created with siae.id={siae.id}.")

    structures_updated = 0
    # Update structures which already exist in database.
    for siret in updatable_sirets:
        siae = Siae.objects.get(siret=siret, kind__in=kinds)
        if siae.source != source:
            # If a user/staff created structure already exists in db and its siret is later found in an export,
            # it makes sense to convert it.
            print(f"siae.id={siae.id} siret={siae.siret} source={siae.source} will be converted to source={source}.")
            siae.source = source
            if wet_run:
                siae.save()
                structures_updated += 1

    # Delete structures which no longer exist in the latest export.
    deleted_count = 0
    undeletable_count = 0
    deletable_skipped_count = 0
    for siret in deletable_sirets:
        siae = Siae.objects.get(siret=siret, kind__in=kinds)

        one_week_ago = timezone.now() - timezone.timedelta(days=7)
        if siae.source == Siae.SOURCE_STAFF_CREATED and siae.created_at >= one_week_ago:
            # When our staff creates a structure, let's give the user sufficient time to join it before deleting it.
            deletable_skipped_count += 1
            continue

        if siae.source == Siae.SOURCE_USER_CREATED:
            # When an employer creates an antenna, it is normal that this antenna cannot be found in official exports.
            # Thus we never attempt to delete it, as long as it has data.
            deletable_skipped_count += 1
            continue

        if could_siae_be_deleted(siae):
            print(f"siae.id={siae.id} siret={siae.siret} will be deleted.")
            if wet_run:
                siae.delete()
                deleted_count += 1
            continue

        # As of 2021/04/15, 2 GEIQ are undeletable.
        # As of 2021/04/15, 8 EA_EATT are undeletable.
        print(f"siae.id={siae.id} siret={siae.siret} source={siae.source} cannot be deleted as it has data.")
        undeletable_count += 1

    print(f"{deleted_count} {source} can and will be deleted.")
    print(f"{undeletable_count} {source} cannot be deleted as they have data.")

    return {
        "creatable_sirets": len(creatable_sirets),
        "updatable_sirets": len(deletable_sirets),
        "deletable_sirets": len(deletable_sirets),
        "not_created_because_of_missing_email": not_created_because_of_missing_email,
        "structures_created": structures_created,
        "structures_updated": structures_updated,
        "structures_deleted": deleted_count,
        "structures_undeletable": undeletable_count,
        "structures_deletable_skipped": deletable_skipped_count,
    }


def anonymize_fluxiae_df(df):
    """
    Drop and/or anonymize sensitive data in fluxIAE dataframe.
    """
    if "salarie_date_naissance" in df.columns.tolist():
        df["salarie_annee_naissance"] = df.salarie_date_naissance.str[-4:].astype(int)

    if "salarie_agrement" in df.columns.tolist():
        df["hash_numéro_pass_iae"] = df["salarie_agrement"].apply(hash_content)

    # Any column having any of these keywords inside its name will be dropped.
    # E.g. if `courriel` is a deletable keyword, then columns named `referent_courriel`,
    # `representant_courriel` etc will all be dropped.
    deletable_keywords = [
        "courriel",
        "telephone",
        "prenom",
        "nom_usage",
        "nom_naissance",
        "responsable_nom",
        "urgence_nom",
        "referent_nom",
        "representant_nom",
        "date_naissance",
        "adr_mail",
        "nationalite",
        "titre_sejour",
        "observations",
        "salarie_agrement",
        "salarie_adr_point_remise",
        "salarie_adr_cplt_point_geo",
        "salarie_adr_numero_voie",
        "salarie_codeextensionvoie",
        "salarie_codetypevoie",
        "salarie_adr_libelle_voie",
        "salarie_adr_cplt_distribution",
        "salarie_adr_qpv_nom",
    ]

    for column_name in df.columns.tolist():
        for deletable_keyword in deletable_keywords:
            if deletable_keyword in column_name:
                del df[column_name]

    # Better safe than sorry when dealing with sensitive data!
    for column_name in df.columns.tolist():
        for deletable_keyword in deletable_keywords:
            assert deletable_keyword not in column_name

    return df


def get_fluxiae_df(
    vue_name,
    converters=None,
    description=None,
    parse_dates=None,
    skip_first_row=True,
    anonymize_sensitive_data=True,
    infer_datetime_format=True,
):
    """
    Load fluxIAE CSV file as a dataframe.
    Any sensitive data will be dropped and/or anonymized.
    """
    filename = get_filename(
        filename_prefix=vue_name,
        filename_extension=".csv",
        description=description,
    )

    # Prepare parameters for pandas.read_csv method.
    kwargs = {}

    if skip_first_row:
        # Some fluxIAE exports have a leading "DEB***" row, some don't.
        kwargs["skiprows"] = 1

    # All fluxIAE exports have a final "FIN***" row which should be ignored. The most obvious way to do this is
    # to use `skipfooter=1` option in `pd.read_csv` however this causes several issues:
    # - it forces the use of the 'python' engine instead of the default 'c' engine
    # - the 'python' engine is much slower than the 'c' engine
    # - the 'python' engine does not play well when faced with special characters (e.g. `"`) inside a row value,
    #   it will break or require the `error_bad_lines=False` option to ignore all those rows

    # Thus we decide to always use the 'c' engine and implement the `skipfooter=1` option ourselves by counting
    # the rows in the CSV file beforehands instead. Always using the 'c' engine is proven to significantly reduce
    # the duration and frequency of the developer's headaches.

    try:
        with gzip.open(filename) as f:
            # Ignore 3 rows: the `DEB*` first row, the headers row, and the `FIN*` last row.
            nrows = -3
            for _line in f:
                nrows += 1
    except gzip.BadGzipFile:
        with zipfile.ZipFile(filename) as f:
            assert len(f.namelist()) == 1
            with f.open(f.namelist()[0]) as ff:
                # Ignore 3 rows: the `DEB*` first row, the headers row, and the `FIN*` last row.
                nrows = -3
                for _line in ff:
                    nrows += 1
        kwargs["compression"] = "zip"  # default compression infer does not detect correctly

    print(f"Loading {nrows} rows for {vue_name} ...")

    if converters:
        kwargs["converters"] = converters

    if parse_dates:
        kwargs["parse_dates"] = parse_dates

    # Removes warnings when automatically parsing dates with pandas.read_csv
    # ex: UserWarning: Parsing '30/04/2023' in DD/MM/YYYY format. Provide format ...
    #     ... or specify infer_datetime_format=True for consistent parsing.
    # See: https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html
    kwargs["infer_datetime_format"] = infer_datetime_format
    # But when guessing, we are more likely to end up with European style dates than American
    # in ASP files
    kwargs["dayfirst"] = True

    df = pd.read_csv(
        filename,
        sep="|",
        # Some rows have a single `"` in a field, for example in fluxIAE_Mission the mission_descriptif field of
        # the mission id 1003399237 is `"AIEHPAD` (no closing double quote). This screws CSV parsing big time
        # as the parser will read many rows until the next `"` and consider all of them as part of the
        # initial mission_descriptif field value o_O. Let's just disable quoting alltogether to avoid that.
        quoting=csv.QUOTE_NONE,
        nrows=nrows,
        **kwargs,
        # Fix DtypeWarning (Columns have mixed types) and avoid error when field value in later rows contradicts
        # the field data format guessed on first rows.
        low_memory=False,
    )

    # If there is only one column, something went wrong, let's break early.
    # Most likely an incorrect skip_first_row value.
    assert len(df.columns.tolist()) >= 2

    assert len(df) == nrows

    if anonymize_sensitive_data:
        df = anonymize_fluxiae_df(df)

    return df
