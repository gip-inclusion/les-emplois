import pandas as pd

from itou.approvals.models import PoleEmploiApproval
from itou.utils.command import BaseCommand


def update_approval(row, wet_run, stdout):
    number = str(row["NUM_AGR_DEC"])  # non contractual column name for the "numéro d'agrément"
    siae_siret = str(row["SIAE_SIRET"])  # same for SIAE SIRET
    siae_kind = str(row["SIAE_KIND"])  # same for SIAE kind

    pe_approval = PoleEmploiApproval.objects.filter(number=number).first()
    if pe_approval:
        if wet_run:
            pe_approval.siae_siret = siae_siret
            pe_approval.siae_kind = siae_kind
            pe_approval.save(update_fields=["siae_siret", "siae_kind"])
        stdout.write(f"> pe_approval={pe_approval} was updated with siret={siae_siret} and kind={siae_kind}")

    else:
        stdout.write(f"! pe_approval with number={number} not found")


class Command(BaseCommand):
    help = "Merges the SIRET and KIND in PoleEmploiApprovals"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file-path",
            dest="file_path",
            required=True,
            action="store",
            help="Absolute path of the XLSX file to import",
        )
        parser.add_argument("--wet-run", action="store_true", dest="wet_run")

    def handle(self, file_path, *, wet_run, **options):
        df = pd.read_excel(file_path)
        self.stdout.write(f"Ready to import up to length={len(df)} approvals from file={file_path}")
        df.apply(lambda row: update_approval(row, wet_run, self.stdout), axis=1)
        self.stdout.write("Done.")
