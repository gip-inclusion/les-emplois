import datetime
import logging
import time
from tempfile import NamedTemporaryFile

from django.conf import settings
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

from itou.job_applications.models import JobApplication


# XLS export of currently valid approvals
# Currently used by admin site and admin command (export_approvals)

logger = logging.getLogger(__name__)

FIELDS = [
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
DATE_FMT = "%d-%m-%Y"
EXPORT_FORMATS = ["stream", "file"]


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
    ws = wb.active

    # These values were formerly computed dynamically in the rendering loop
    # It is *way* faster to use static values to change the width of columns once
    max_widths = [14, 39, 33, 14, 15, 19, 17, 11, 37, 21, 14, 73, 9, 19, 19]
    current_dt = datetime.datetime.now()
    ws.title = "Export PASS SIAE " + current_dt.strftime(DATE_FMT)

    logger.info("Loading data...")
    st = time.clock()

    # Fetch data
    job_applications = JobApplication.objects.exclude(approval=None).select_related(
        "job_seeker", "approval", "to_siae"
    )

    export_count = job_applications.count()

    # Write header line
    for idx, cell_value in enumerate(FIELDS, 1):
        ws.cell(1, idx).value = cell_value

    # Write data rows
    for row_idx, ja in enumerate(job_applications.iterator(), 2):
        line = [
            ja.job_seeker.pole_emploi_id,
            ja.job_seeker.first_name,
            ja.job_seeker.last_name,
            ja.job_seeker.birthdate.strftime(DATE_FMT),
            ja.approval.number,
            ja.approval.start_at.strftime(DATE_FMT),
            ja.approval.end_at.strftime(DATE_FMT),
            ja.job_seeker.post_code,
            ja.job_seeker.city,
            ja.to_siae.post_code,
            ja.to_siae.siret,
            ja.to_siae.name,
            ja.to_siae.kind,
            ja.hiring_start_at.strftime(DATE_FMT) if ja.hiring_start_at else "",
            ja.hiring_end_at.strftime(DATE_FMT) if ja.hiring_end_at else "",
        ]
        # Instead of using a temp array to store lines,
        # write rows one by one
        for col_idx, cell_value in enumerate(line, 1):
            ws.cell(row_idx, col_idx).value = cell_value

    # Formating columns once (not in the loop)
    for idx, width in enumerate(max_widths, 1):
        ws.column_dimensions[get_column_letter(idx)].width = width

    logger.info(f"Exported {export_count} records")
    logger.info(f"Took: {time.clock() - st} sec.")

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
