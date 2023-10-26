import csv
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from tqdm import tqdm

from itou.approvals.models import PoleEmploiApproval
from itou.utils.command import BaseCommand
from itou.utils.validators import validate_nir


# This is the same kind of export as for the management command "import_ai_employees",
# they share a common semi-cryptic naming
FIRST_NAME_COL = "pph_prenom"
LAST_NAME_COL = "pph_nom_usage"
APPROVAL_COL = "agr_numero_agrement"
NIR_COL = "ppn_numero_inscription"
# Those columns differ from the AI export
PASS_IAE_NUMBER_COL = "PASS IAE"
PASS_IAE_START_DATE_COL = "Date de début PASS IAE"
PASS_IAE_END_DATE_COL = "Date de fin PASS IAE"


@dataclass
class PeBeneficiaire:
    prenom: str
    nom_usage: str
    nir: str
    agrement: str
    numero_pass: str

    @classmethod
    def from_row(cls, row):
        return cls(
            prenom=row[FIRST_NAME_COL],
            nom_usage=row[LAST_NAME_COL],
            agrement=row[APPROVAL_COL],
            numero_pass=row[PASS_IAE_NUMBER_COL],
            nir=row[NIR_COL],
        )


class Command(BaseCommand):
    """
    ./manage.py update_pe_approvals_from_asp_data --dry-run

    Ajoute le NIR ou le NIA/NTT dans les objets PoleEmploiApproval à partir de l’export fourni par l’ASP.
    Croise les infos à partir du numéro de pass.

    Cette import est la suite de update_nir_from_pe_data (qui importait l’essentiel des données, mais n’arrivait pas à
    trouver tous les candidats). Il est construit sur le même modèle.
    """

    queue = []
    errors = []
    found_pe_approvals = 0
    updated_pe_approval = 0
    nb_nir = 0
    nb_ntt_nia = 0
    agrement_not_found = []

    def process(self, beneficiaire: PeBeneficiaire):
        """
        At this point:
            - we only want to find the PoleEmploiApproval by their "numero d’agrement".
            This number can be 12 or 15 digits long. The 15-digit version is the same as
            the 12 but has a suffix
            - we choose not to use the pole_emploi_id contained in the excel export,
            due to the low quality of the data.
        """
        pe_approvals = PoleEmploiApproval.objects.filter(number__startswith=beneficiaire.agrement[:12])
        if len(pe_approvals) > 0:
            for pe_approval in pe_approvals:
                if self.validate(pe_approval, beneficiaire):
                    self.prepare_update_pe_approval(beneficiaire, pe_approval)

            self.found_pe_approvals += 1
        else:
            self.agrement_not_found.append(
                {
                    "pe_numero_agrement": beneficiaire.agrement,
                    "pe_nir": beneficiaire.nir,
                }
            )

    def validate(self, pe_approval, beneficiaire):
        # We match with `in` instead of == : often, everything matches except the first name
        # …but’s it quite close anyway so we assume it OK, eg: MARIE NADINE / MARIE
        if (
            pe_approval.first_name.strip() != beneficiaire.prenom.strip()
            or pe_approval.birth_name.strip() != beneficiaire.nom_usage.strip()
        ):
            self.errors.append(
                {
                    "pe_approval_id": pe_approval.id,
                    "beneficiaire_nir": beneficiaire.nir,
                    "pe_approval.numero_agrement": pe_approval.number,
                    "beneficiaire_numero_agrement": beneficiaire.agrement,
                    "pe_approval_pole_emploi_id": pe_approval.pole_emploi_id,
                    "agrement_prenom": pe_approval.first_name,
                    "beneficiaire_prenom": beneficiaire.prenom,
                }
            )
            return False
        return True

    def prepare_update_pe_approval(self, beneficiaire: PeBeneficiaire, pe_approval: PoleEmploiApproval):
        try:
            validate_nir(beneficiaire.nir)
            pe_approval.nir = beneficiaire.nir
            self.nb_nir += 1
        except ValidationError as e:  # noqa
            pe_approval.ntt_nia = beneficiaire.nir
            self.nb_ntt_nia += 1
        self.updated_pe_approval += 1
        if not self.dry_run:
            self.queue.append(pe_approval)
            self.dump_queue()

    def dump_queue(self, force_dump=False):
        # The queue size is set to a low number > 1 in order to:
        # - minimize the amount of updates
        # - not crash. With 10000, the update hangs
        if not self.dry_run and (force_dump or len(self.queue) > 1000):
            PoleEmploiApproval.objects.bulk_update(self.queue, ["nir", "ntt_nia"])
            self.queue = []

    def dump_errors(self):
        if len(self.errors) > 0:
            cols = self.errors[0].keys()
            csv_writer = csv.DictWriter(self.stdout, cols)
            csv_writer.writeheader()
            csv_writer.writerows(self.errors)

    def dump_agrements_not_found(self):
        if len(self.agrement_not_found) > 0:
            with open("agrements_not_found.csv", "w") as outfile:
                cols = self.agrement_not_found[0].keys()
                csv_writer = csv.DictWriter(outfile, cols)
                csv_writer.writeheader()
                csv_writer.writerows(self.agrement_not_found)

    def add_arguments(self, parser):
        parser.add_argument(
            "--file-path",
            dest="file_path",
            required=True,
            action="store",
            help="Absolute path of the file to import",
        )
        parser.add_argument(
            "--dry-run", dest="dry_run", action="store_true", help="Only print possible errors and stats"
        )

    def handle(self, file_path, *, dry_run, **options):
        self.dry_run = dry_run
        self.stdout.write("Importing NIR from ASP data.")
        # The fastest way I’ve found to parse this file is to use a CsvDictReader with a CSV file
        # akin to what I do in update_nir_from_pe_data
        # See https://pandas.pydata.org/pandas-docs/version/1.0.0/user_guide/io.html#io-xlsb

        nb_lines = 0
        with open(file_path, newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            beneficiaires = [PeBeneficiaire.from_row(row) for row in reader]
            pbar = tqdm(total=len(beneficiaires))
            # Running this is still very slow because we have to find the rows individually
            # and I’ve found no simple way to make the retrieval/update very fast.
            # Total running time for 405_000 rows: ~4mn
            nb_lines = len(beneficiaires)
            for beneficiaire in beneficiaires:
                pbar.update(1)
                self.process(beneficiaire)
            pbar.close()
        self.dump_queue(force_dump=True)
        self.dump_errors()
        self.dump_agrements_not_found()

        self.stdout.write(f"nb rows in export: {nb_lines}")
        self.stdout.write(f"nb found pe approvals: {self.found_pe_approvals}")
        self.stdout.write(f"nb updated: {self.updated_pe_approval}")
        self.stdout.write(f"nb nir: {self.nb_nir}")
        self.stdout.write(f"nb ntt_nia: {self.nb_ntt_nia}")
