import csv
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from tqdm import tqdm

from itou.approvals.models import PoleEmploiApproval
from itou.utils.command import BaseCommand
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
    ./manage.py update_nir_from_pe_data --file-path="./imports/LISTE_IAE_NIR_PNI-pruned-from-fluff.csv" --dry-run

    Ajoute le NIR ou le NIA/NTT dans les objets PoleEmploiApproval à partir de l’export LISTE_IAE_NIR_PNI.
    Croise les infos à partir du numéro de pass
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
            pe_approvals_by_pe_id = PoleEmploiApproval.objects.filter(pole_emploi_id=beneficiaire.pole_emploi_id)
            if len(pe_approvals_by_pe_id) > 0:
                for approval in pe_approvals_by_pe_id:
                    self.agrement_not_found.append(
                        {
                            "pe_pole_emploi_id": beneficiaire.pole_emploi_id,
                            "pe_prenom": beneficiaire.prenom,
                            "pe_nom_naissance": beneficiaire.nom_naissance,
                            "pe_numero_agrement": beneficiaire.agrement,
                            "itou_numero_agrement": approval.number,
                            "itou_prenom": approval.first_name,
                            "itou_nom_naissance": approval.birth_name,
                            "pe_nir": beneficiaire.nir,
                        }
                    )
            else:
                self.agrement_not_found.append(
                    {
                        "pe_pole_emploi_id": beneficiaire.pole_emploi_id,
                        "pe_prenom": beneficiaire.prenom,
                        "pe_nom_naissance": beneficiaire.nom_naissance,
                        "pe_numero_agrement": beneficiaire.agrement,
                        "itou_numero_agrement": "",
                        "itou_prenom": "",
                        "itou_nom_naissance": "",
                        "pe_nir": beneficiaire.nir,
                    }
                )

    def validate(self, pe_approval, beneficiaire):
        # We match with `in` instead of == : often, everything matches except the first name
        # …but’s it quite close anyway so we assume it OK, eg: MARIE NADINE / MARIE
        if (
            pe_approval.first_name.strip() not in beneficiaire.prenom.strip()
            or pe_approval.birth_name.strip() not in beneficiaire.nom_naissance.strip()
        ):
            self.errors.append(
                {
                    "pe_approval_id": pe_approval.id,
                    "beneficiaire_nir": beneficiaire.nir,
                    "pe_approval.numero_agrement": pe_approval.number,
                    "beneficiaire_numero_agrement": beneficiaire.agrement,
                    "pe_approval_pole_emploi_id": pe_approval.pole_emploi_id,
                    "beneficiaire_pole_emploi_id": beneficiaire.pole_emploi_id,
                    "agrement_prenom": pe_approval.first_name,
                    "beneficiaire_prenom": beneficiaire.prenom,
                    "agrement_nom_naissance": pe_approval.birth_name,
                    "beneficiaire_nom_naissance": beneficiaire.nom_naissance,
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
        self.stdout.write("Exporting approvals / PASS IAE")
        # The fastest way I’ve found to parse this file is to use a CsvDictReader with a CSV file
        # where I manually pruned all the useless columns (~3s):
        # file_path="./imports/LISTE_IAE_NIR_PNI-pruned-from-fluff.csv"
        #  - pandas can do that too, but simply opening the file is crazy slow (2mn5 for me).
        #  - using pyxlsb allows us to open the file in ~19s, but then we have to process the rows ourselves,
        #  and the DX is not that great (see https://github.com/willtrnr/pyxlsb)
        #
        # Both pandas and pyxlsb require to add pyxlsb as a dependency which is not that great for a one-off script.
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
        # self.dump_errors()
        self.dump_agrements_not_found()

        self.stdout.write(f"nb rows in export: {nb_lines}")
        self.stdout.write(f"nb found pe approvals: {self.found_pe_approvals}")
        self.stdout.write(f"nb updated: {self.updated_pe_approval}")
        self.stdout.write(f"nb nir: {self.nb_nir}")
        self.stdout.write(f"nb ntt_nia: {self.nb_ntt_nia}")
