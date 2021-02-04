import datetime
import logging
import time
from tempfile import NamedTemporaryFile

from django.conf import settings
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

from itou.job_applications.models import JobApplication, Suspension


# XLS export of approvals
# Currently used by admin site and admin command (export_approvals)

logger = logging.getLogger(__name__)

# Field names for worksheet 1 (full export of approvals)
FIELDS_WS1 = [
    "id_pole_emploi",
    "nom",
    "prenom",
    "date_naissance",
    "numero_pass_iae",
    "date_debut_pass_iae",
    "date_fin_pass_iae",
    "code_postal",
    "ville",
    "code_postal_employeur",
    "numero_siret",
    "raison_sociale",
    "type_siae",
    "date_debut_embauche",
    "date_fin_embauche",
]

# These values were formerly computed dynamically in the rendering loop
# It is *way* faster to use static values to change the width of columns once
WIDTHS_WS1 = [14, 39, 33, 14, 15, 19, 17, 11, 37, 21, 14, 73, 9, 19, 19]

# Field names for worksheet 2 (approvals suspensions)
FIELDS_WS2 = [
    "numero_pass_iae",
    "date_debut_suspension",
    "date_fin_suspension",
    "raison",
    "suspendu_par",
    "numero_siret",
    "raison_sociale",
]
# Columns widths for worksheet 2
WIDTHS_WS2 = [16, 20, 20, 50, 40, 20, 80]

DATE_FMT = "%d-%m-%Y"
EXPORT_FORMATS = ["stream", "file"]


def _format_date(dt):
    return dt.strftime(DATE_FMT) if dt else ""


def _format_pass_worksheet(wb):
    """
    Export of all approvals
    """
    logger.info("Loading approvals data...")

    ws = wb.active
    current_dt = datetime.datetime.now()
    ws.title = "Export PASS IAE " + current_dt.strftime(DATE_FMT)

    # Start timer
    st = time.clock()

    job_applications = JobApplication.objects.exclude(approval=None).select_related(
        "job_seeker", "approval", "to_siae"
    )

    # Write header line
    for idx, cell_value in enumerate(FIELDS_WS1, 1):
        ws.cell(1, idx).value = cell_value

    # Write data rows
    for row_idx, ja in enumerate(job_applications.iterator(), 2):
        line = [
            ja.job_seeker.pole_emploi_id,
            ja.job_seeker.first_name,
            ja.job_seeker.last_name,
            _format_date(ja.job_seeker.birthdate),
            ja.approval.number,
            _format_date(ja.approval.start_at),
            _format_date(ja.approval.end_at),
            ja.job_seeker.post_code,
            ja.job_seeker.city,
            ja.to_siae.post_code,
            ja.to_siae.siret,
            ja.to_siae.name,
            ja.to_siae.kind,
            _format_date(ja.hiring_start_at),
            _format_date(ja.hiring_end_at),
        ]
        # Instead of using a temp array to store lines,
        # writing rows one by one will avoid memory issues
        for col_idx, cell_value in enumerate(line, 1):
            ws.cell(row_idx, col_idx).value = cell_value

    # Formating columns once (not in the loop)
    for idx, width in enumerate(WIDTHS_WS1, 1):
        ws.column_dimensions[get_column_letter(idx)].width = width

    export_count = job_applications.count()

    logger.info(f"Exported {export_count} approvals in {time.clock() - st} sec.")


def _format_suspended_pass_worksheet(wb):
    """
    Suspended approvals
    """
    # suspended_approvals = Suspension.objects.all().select_related("approval")
    # suspended_count = suspended_approvals.count()
    logger.info("Loading suspension data...")

    ws = wb.create_sheet("Suspensions PASS IAE")

    # Start timer
    st = time.clock()

    suspensions = Suspension.objects.all().select_related("approval", "created_by")

    # Write header line
    for idx, cell_value in enumerate(FIELDS_WS2, 1):
        ws.cell(1, idx).value = cell_value

    for idx, s in enumerate(suspensions.iterator(), 2):
        line = [
            s.approval.number,
            _format_date(s.start_at),
            _format_date(s.end_at),
            s.get_reason_display(),
            s.created_by.email,
            s.siae.siret,
            s.siae.name,
        ]
        for col_idx, cell_value in enumerate(line, 1):
            ws.cell(idx, col_idx).value = cell_value

    # Formating columns once (not in the loop)
    for idx, width in enumerate(WIDTHS_WS2, 1):
        ws.column_dimensions[get_column_letter(idx)].width = width

    export_count = suspensions.count()
    logger.info(f"Exported {export_count} suspensions in {time.clock() - st} sec.")


def export_approvals(export_format="file"):
    """
    Main entry point. Currently used by admin site and an admin command:
        $ itou/approvals/management/commands/export_approvals.py

    `export_format` can be either:
        * `file` : for the admin command, export result as a file
        * `stream` : for the admin site (to be bundled in a HTTP response object)

    Returns:
        * a path for `file`
        * a pair with filename and object for `stream`
    """
    assert export_format in EXPORT_FORMATS, f"Unknown export format '{export_format}'"

    wb = Workbook()
    _format_pass_worksheet(wb)
    _format_suspended_pass_worksheet(wb)

    current_dt = datetime.datetime.now()
    suffix = current_dt.strftime("%d%m%Y_%H%M%S")
    filename = f"export_pass_iae_{suffix}.xlsx"

    if export_format == "file":
        path = f"{settings.EXPORT_DIR}/{filename}"
        wb.save(path)
        return path
    elif export_format == "stream":
        # save_virtual_workbook is deprecated
        with NamedTemporaryFile() as tmp_file:
            wb.save(tmp_file.name)
            tmp_file.seek(0)
            return filename, tmp_file.read()
