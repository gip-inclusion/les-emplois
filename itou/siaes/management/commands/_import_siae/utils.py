"""

Various helpers shared by the import_siae, import_geiq and import_ea_eatt scripts.

"""
import os
from functools import wraps
from time import time

from django.utils import timezone

from itou.siaes.models import Siae
from itou.utils.address.models import AddressMixin
from itou.utils.apis.geocoding import get_geocoding_data


CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

SHOW_IMPORT_SIAE_METHOD_TIMER = False


def timeit(f):
    """
    Quick and dirty method timer (as a decorator).
    Could not make it work easily with the `import_siae.Command` class.
    Thus dirty becauses uses `print` instead of `self.log`.

    Maybe later we can use this builtin timer instead:
    https://docs.python.org/3/library/timeit.html#python-interface
    """

    @wraps(f)
    def wrap(*args, **kw):
        ts = time()
        result = f(*args, **kw)
        te = time()
        msg = f"Method {f.__name__} took {te - ts:.2f} seconds to complete"
        if SHOW_IMPORT_SIAE_METHOD_TIMER:
            print(msg)
        return result

    return wrap


def get_filename(filename_prefix, filename_extension, description):
    """
    Automatically detect the correct filename.
    e.g. fluxIAE_Structure_14122020_075350.csv
    e.g. fluxIAE_AnnexeFinanciere_14122020_063002.csv
    """
    filenames = []
    path = f"{CURRENT_DIR}/../data"
    for filename in os.listdir(path):
        root, ext = os.path.splitext(filename)
        if root.startswith(filename_prefix) and ext == filename_extension:
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
    s = s.strip()
    return " ".join(s.split())


def remap_columns(df, column_mapping):
    """
    Rename columns according to mapping and delete all other columns.

    Example of column_mapping :

    {"ID Structure": "asp_id", "Adresse e-mail": "auth_email"}
    """
    df.rename(
        columns=column_mapping, inplace=True,
    )

    # Keep only the columns we need.
    df = df[column_mapping.values()]

    return df


def could_siae_be_deleted(siae):
    return siae.members.count() == 0 and siae.job_applications_received.count() == 0


def geocode_siae(siae):
    if siae.geocoding_address is None:
        return siae

    geocoding_data = get_geocoding_data(siae.geocoding_address, post_code=siae.post_code)

    if geocoding_data:
        siae.geocoding_score = geocoding_data["score"]
        # If the score is greater than API_BAN_RELIABLE_MIN_SCORE, coords are reliable:
        # use data returned by the BAN API because it's better written using accents etc.
        # while the source data is in all caps etc.
        # Otherwise keep the old address (which is probably wrong or incomplete).
        if siae.geocoding_score >= AddressMixin.API_BAN_RELIABLE_MIN_SCORE:
            siae.address_line_1 = geocoding_data["address_line_1"]
        # City is always good due to `postcode` passed in query.
        # ST MAURICE DE REMENS => Saint-Maurice-de-Rémens
        siae.city = geocoding_data["city"]

        siae.coords = geocoding_data["coords"]

    return siae


def sync_structures(df, name, kinds, build_structure, dry_run):
    """
    Sync structures between db and export.

    The same logic here is shared between import_geiq and import_ea_eatt.

    - df: dataframe of structures, one row per structure
    - name: user friendly name ("GEIQ" or "EA and EATT")
    - kinds: possible kinds of the structures
    - build_structure: a method building a structure from a dataframe row
    """
    print(f"Loaded {len(df)} {name} from export.")

    db_sirets = set([siae.siret for siae in Siae.objects.filter(kind__in=kinds)])
    df_sirets = set(df.siret.tolist())

    # Create structures which do not exist in database yet.
    creatable_sirets = df_sirets - db_sirets
    print(f"{len(creatable_sirets)} {name} will be created.")
    siret_to_row = {row.siret: row for _, row in df.iterrows()}
    for siret in creatable_sirets:
        row = siret_to_row[siret]
        siae = build_structure(row)
        if not dry_run:
            siae.save()
            print(f"siae.id={siae.id} has been created.")

    # Delete structures which no longer exist in the latest export.
    deletable_sirets = db_sirets - df_sirets
    print(f"{len(deletable_sirets)} {name} will be deleted.")
    for siret in deletable_sirets:
        siae = Siae.objects.get(siret=siret, kind__in=kinds)

        one_week_ago = timezone.now() - timezone.timedelta(days=7)
        if siae.source == Siae.SOURCE_STAFF_CREATED and siae.created_at >= one_week_ago:
            print(f"siae.id={siae.id} is staff created and too recent to be deleted.")
            continue

        if could_siae_be_deleted(siae):
            print(f"siae.id={siae.id} will be deleted.")
            if not dry_run:
                siae.delete()
            continue

        # As of 2020/10/16, 5 GEIQ are undeletable.
        # As of 2020/12/11, 5 EA and EATT are undeletable.
        print(f"siae.id={siae.id} cannot be deleted as it has data.")
