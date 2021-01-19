import datetime
import time
from tempfile import NamedTemporaryFile

from django.conf import settings
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

from itou.job_applications.models import JobApplication


# XLS export of currently valid approvals
# Currently used by admin site and admin command (export_approvals)

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

    current_dt = datetime.datetime.now()
    ws.title = "Export PASS SIAE " + current_dt.strftime(DATE_FMT)

    print("Loading data...")
    data = [FIELDS]

    st = time.clock()

    # Let try
    job_applications = JobApplication.objects.exclude(approval=None).select_related(
        "job_seeker", "approval", "to_siae"
    )

    for ja in job_applications:
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
        ]
        data.append(line)

    print(f"Took: {time.clock() - st} sec.")

    # These values were formerly computed dynamically in the rendering loop
    # It is *way* faster to use static values to change the width of columns once
    max_widths = [14, 39, 33, 14, 15, 19, 17, 11, 37, 21, 14, 73, 9]

    print("Writing data...")
    st = time.clock()
    for i, row in enumerate(data, 1):
        for j, cell_value in enumerate(row, 1):
            ws.cell(i, j).value = cell_value

    # Formating columns once (not in the loop)
    for idx, width in enumerate(max_widths, 1):
        ws.column_dimensions[get_column_letter(idx)].width = width

    print(f"Took: {time.clock() - st} sec.")

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
