from django.core.management.base import BaseCommand
from django.db import connection
from openpyxl import load_workbook
from psycopg2 import sql  # noqa
from tqdm import tqdm

from itou.users.models import User


def get_worksheet_height(worksheet):
    # openpyxl worksheet.max_row does not return the max index with data,
    # but some max index which is not useful to us
    # https://stackoverflow.com/a/56322613
    count = 0
    for row in worksheet:
        if not all([cell.value is None for cell in row]):
            count += 1

    return count


class Command(BaseCommand):
    """
    ./manage.py improve_asp_db --reset
    Complète le fichier de l'ASP (20220120_sans_doublons)
    avec les bonnes infos qui sont désormais chez nous.
    on re-remplit les colonnes de ce fichier :
        - Y (PASS IAE)
        - Z (Date de début PASS IAE)
        - AA (Date de fin PASS IAE) , en utilisant
    On utilise la colonne E (ppn_numero_inscription) qui contient le NIR pour croiser
    """

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", dest="dry_run", action="store_true", help="Only print possible errors and stats"
        )

    def find_agrement_data_by_nir(self, nir):
        """
        We’ve got the NIR (or possibly NTT/NIA) of a condidate,
        we want to return the agrement number, as well as it start and end date

        In order to do this, we first try to  use the (not yet deployed, hence the raw SQL)
        merged_approvals_poleemploiapproval table.
        If we do not find the candidate there, we run through the User model directly, and go through the approvals
        """
        search_sql = """select
                left(number, 12),
                start_at,
                end_at
            from merged_approvals_poleemploiapproval
            where nir=%s or ntt_nia=%s"""
        self.cursor.execute(search_sql, [nir, nir])
        res = self.cursor.fetchone()
        if res is not None:
            number, start_at, end_at = res[0], res[1], res[2]
            return (number, start_at, end_at)
        else:
            try:
                u = User.objects.get(nir=nir)  # noqa
                approval = u.approvals_wrapper.latest_approval
                if approval is not None:
                    return approval.number, approval.start_at, approval.end_at
                else:
                    raise ValueError("Approval non trouvee")

            except User.DoesNotExist:
                raise ValueError("Nir non trouve")

    def handle(self, dry_run=False, reset=False, **options):
        self.dry_run = dry_run
        self.stdout.write("Merging approvals / PASS IAE")
        self.cursor = connection.cursor()
        filename = "exports/20220120_sans_doublons.xlsx"
        # filename = "exports/20220120_sans_doublons-small.xlsx"
        out = "exports/20220120_enrichi.xlsx"

        workbook = load_workbook(filename=filename)
        worksheet = workbook.active
        total = get_worksheet_height(worksheet)
        progressbar = tqdm(total=total)
        for row in range(2, total):
            numero_agrement_index = f"Y{row}"
            date_debut_index = f"Z{row}"
            date_fin_index = f"AA{row}"

            try:
                nir_index = f"E{row}"
                nir = worksheet[nir_index].value
                number, start_at, end_at = self.find_agrement_data_by_nir(nir)

                worksheet[numero_agrement_index] = number
                worksheet[date_debut_index] = start_at
                worksheet[date_fin_index] = end_at

            except ValueError:
                worksheet[numero_agrement_index] = ""
                worksheet[date_debut_index] = ""
                worksheet[date_fin_index] = ""

            progressbar.update(1)

        workbook.save(out)
        progressbar.close()
