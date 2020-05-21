import datetime

from django.conf import settings
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.writer.excel import save_virtual_workbook

from itou.approvals.models import Approval


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
    "code_postal_employeur",
    "numero_siret",
    "raison_sociale",
]
DATE_FMT = "%d-%m-%Y"
EXPORT_FORMATS = ["stream", "file"]


def export_approvals(export_format="file"):
    """
    Main entry point. Currently used by admin site and an admin command (`itou/approvals/management/commands/export_approvals.py`)

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

    data = [FIELDS]
    approvals = Approval.objects.all().select_related("user").prefetch_related("jobapplication_set__to_siae")

    for approval in approvals:
        # The same approval can be used for multiple job applications.
        for job_application in approval.jobapplication_set.all():
            line = [
                approval.user.pole_emploi_id,
                approval.user.first_name,
                approval.user.last_name,
                approval.user.birthdate.strftime(DATE_FMT),
                approval.number,
                approval.start_at.strftime(DATE_FMT),
                approval.end_at.strftime(DATE_FMT),
                approval.user.post_code,
                job_application.to_siae.post_code,
                job_application.to_siae.siret,
                job_application.to_siae.name,
            ]
            data.append(line)

    # Getting the column to auto-adjust to max field size
    max_width = [0] * (len(FIELDS) + 1)

    for i, row in enumerate(data, 1):
        for j, cell_value in enumerate(row, 1):
            max_width[j] = max(max_width[j], len(cell_value))
            ws.cell(i, j).value = cell_value
            ws.column_dimensions[get_column_letter(j)].width = max_width[j]

    suffix = current_dt.strftime("%d%m%Y_%H%M%S")
    filename = f"export_pass_iae_{suffix}.xlsx"

    if export_format == "file":
        path = f"{settings.EXPORT_DIR}/{filename}"
        wb.save(path)
        return path
    elif export_format == "stream":
        return filename, save_virtual_workbook(wb)
