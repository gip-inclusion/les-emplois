import csv
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from tqdm import tqdm

from itou.approvals.models import PoleEmploiApproval
from itou.utils.validators import validate_nir


@dataclass
class PeBeneficiaire:
    nom_usage: str
    nom_naissance: str
    prenom: str
    nir: str
    agrement: str
    pole_emploi_id: str

    @classmethod
    def from_row(cls, row):
        # Liste des colonnes du fichier CSV:
        # ID_REGIONAL_BENE	NOM_USAGE_BENE	NOM_NAISS_BENE	PRENOM_BENE
        # DATE_NAISS_BENE	NUM_AGR_DEC	DATE_FIN	DC_NIR	DC_ADRESSEEMAIL
        # pe_approval.pe_structure_code = CODE_STRUCT_AFFECT_BENE
        # pe_approval.birthdate = DATE_NAISS_BENE
        # pe_approval.start_at = DATE_DEB_AGR_DEC
        # pe_approval.end_at = DATE_FIN_AGR_DEC
        return cls(
            nom_usage=row["NOM_USAGE_BENE"],
            nom_naissance=row["NOM_NAISS_BENE"],
            prenom=row["PRENOM_BENE"],
            agrement=row["NUM_AGR_DEC"].replace(" ", ""),
            nir=row["DC_NIR"],
            pole_emploi_id=row["ID_REGIONAL_BENE"],
            # pole_emploi_code_structure=row["CODE_STRUCT_AFFECT_BENE"],
            # birthdate=parse_birthdate(row["DATE_NAISS_BENE"])
        )


class Command(BaseCommand):
    """
    Ajoute le nir dans les objets PoleEmploiApproval à partir de l’export LISTE_IAE_NIR_PNI.
    Croise les infos à partir du numéro de pass ou numéro PE
    """

    queue = []
    errors = []

    def process(self, beneficiaire: PeBeneficiaire):
        try:
            pe_approval = PoleEmploiApproval.objects.get(number=beneficiaire.agrement)
            if self.validate(pe_approval, beneficiaire):
                self.prepare_update_pe_approval(beneficiaire, pe_approval)
        except PoleEmploiApproval.DoesNotExist:
            pe_approvals = PoleEmploiApproval.objects.filter(pole_emploi_id=beneficiaire.pole_emploi_id)
            if len(pe_approvals) == 0:
                return 0
            else:
                for pe_approval in pe_approvals:
                    if self.validate(pe_approval, beneficiaire):
                        self.prepare_update_pe_approval(beneficiaire, pe_approval)
        return 1

    def validate(self, pe_approval, beneficiaire):
        if (
            pe_approval.first_name.strip() not in beneficiaire.prenom.strip()
            or pe_approval.birth_name.strip() not in beneficiaire.nom_naissance.strip()
        ):
            self.errors.append(
                {
                    "pe_approval.id": pe_approval.id,
                    "beneficiaire_nir": beneficiaire.nir,
                    "pe_approval.numero_agrement": pe_approval.number,
                    "beneficiaire_numero_agrement": beneficiaire.agrement,
                    "pe_approval_pole_emploi_id": pe_approval.pole_emploi_id,
                    "beneficiaire_pole_emploi_id": beneficiaire.pole_emploi_id,
                    "beneficiaire_prenom": beneficiaire.prenom,
                    "agrement_prenom": pe_approval.first_name,
                    "beneficiaire_nom_naissance": beneficiaire.nom_naissance,
                    "agrement_nom_naissance": pe_approval.birth_name,
                }
            )
            return False
        return True

    def prepare_update_pe_approval(self, beneficiaire: PeBeneficiaire, pe_approval: PoleEmploiApproval):
        try:
            validate_nir(beneficiaire.nir)
            pe_approval.nir = beneficiaire.nir
        except ValidationError as e:  # noqa
            pe_approval.nia_ntt = beneficiaire.nir

        if not self.dry_run:
            self.queue.append(pe_approval)
            self.dump_queue()

    def dump_queue(self, force_dump=False):
        if force_dump or len(self.queue) > 1000:
            PoleEmploiApproval.objects.bulk_update(self.queue, ["nir", "ntt_nia"])
            self.queue = []

    def dump_errors(self):
        if len(self.errors) > 0:
            cols = self.errors[0].keys()
            csv_writer = csv.DictWriter(self.stdout, cols)
            csv_writer.writeheader()
            csv_writer.writerows(self.errors)

    def add_arguments(self, parser):
        parser.add_argument(
            "--file-path",
            dest="file_path",
            required=True,
            action="store",
            help="Absolute path of the XLSX file to import",
        )
        parser.add_argument(
            "--dry-run", dest="dry_run", action="store_true", help="Only print possible errors and stats"
        )

    def handle(self, file_path, dry_run=False, **options):
        self.dry_run = dry_run
        self.stdout.write("Exporting approvals / PASS IAE")
        # The fastest way to parse this file was is to use a CsvDictReader with a CSV file
        # where I manually pruned all the useless columns (~3s):
        # file_path="./imports/LISTE_IAE_NIR_PNI-pruned-from-fluff.csv"
        #  - pandas can do that too, but simply opening the file is crazy slow (2mn5 for me).
        #  - using pyxlsb allows us to open the file in ~19s, but then we have to process the rows ourselves,
        #  and the DX is not that great (see https://github.com/willtrnr/pyxlsb)
        #
        # Both pandas and pyxlsb require to add pyxlsb as a dependency which is not that great for a one-off script.
        # See https://pandas.pydata.org/pandas-docs/version/1.0.0/user_guide/io.html#io-xlsb

        nb_lines = 0
        nb_found = 0
        nb_valid_nir = 0
        with open(file_path, newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            beneficiaires = [PeBeneficiaire.from_row(row) for row in reader]
            pbar = tqdm(total=len(beneficiaires))
            # The running is still very slow because we have to find the rows individually and there is no simple way
            # to make the retrieval very fast. Total running time for 405_000 rows: ~4mn
            for beneficiaire in beneficiaires:
                pbar.update(1)
                nb_lines += 1
                nb_found += self.process(beneficiaire)
            pbar.close()
        self.dump_queue(force_dump=True)
        self.dump_errors()

        self.stdout.write(f"nb rows: {nb_lines}")
        self.stdout.write(f"nb pe approvals: {nb_found}")
        self.stdout.write(f"nb valid nirs: {nb_valid_nir}")
