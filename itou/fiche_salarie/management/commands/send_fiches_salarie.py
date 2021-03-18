"""
FIXME
"""
import json
import logging
import random

import pysftp
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.crypto import salted_hmac

from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.siaes.models import Siae


class Command(BaseCommand):
    """
    FIXME
    """

    help = "FIXME."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="FIXME")

    def set_logger(self, verbosity):
        """
        Set logger level based on the verbosity option.
        """
        handler = logging.StreamHandler(self.stdout)

        self.logger = logging.getLogger(__name__)
        self.logger.propagate = False
        self.logger.addHandler(handler)

        self.logger.setLevel(logging.INFO)
        if verbosity > 1:
            self.logger.setLevel(logging.DEBUG)

    def log(self, message):
        self.logger.debug(message)

    def get_fiche_salarie_from_hiring(self, hiring):
        assert hiring.state == JobApplicationWorkflow.STATE_ACCEPTED

        siae = hiring.to_siae
        assert siae.source == Siae.SOURCE_ASP
        assert siae.kind in Siae.ELIGIBILITY_REQUIRED_KINDS

        job_seeker = hiring.job_seeker
        assert job_seeker

        diagnosis = job_seeker.eligibility_diagnoses.first()
        assert diagnosis

        approval = hiring.approval
        assert approval

        physical_person = {
            "passIae": approval.number,
            "sufPassIae": None,
            "idItou": salted_hmac(
                key_salt="job_seeker.id", value=job_seeker.id, secret=settings.SECRET_KEY
            ).hexdigest()[:30],
            "civilite": "M",
            "nomUsage": "DECAILLOUX",
            # Optional.
            "nomNaissance": None,
            "prenom": "YVES",
            "dateNaissance": "01/08/1954",
            "codeComInsee": {
                # Birth info.
                # ref_insee_com_v1.csv
                "codeComInsee": "34172",
                # Birth info.
                # ref_insee_dpt_v2.csv
                "codeDpt": "034",
            },
            # Birth info.
            # ref_insee_pays_v4.csv
            "codeInseePays": "100",
            # Nationalité - FIXME only French?
            # ref_grp_pays_v1.csv
            "codeGroupePays": "1",
        }

        address = {
            # Optional.
            "adrTelephone": "0123456789" if job_seeker.phone else None,
            # Optional.
            "adrMail": "john.doe@gmail.com",
            # Current residence info. Not to be confused with birth info.
            # Optional.
            "adrNumeroVoie": None,
            # Optional.
            # ref_extension_voie_v1.csv
            "codeextensionvoie": None,
            # Mandatory.
            # ref_type_voie_v3.csv
            "codetypevoie": "AV",
            # Mandatory.
            "adrLibelleVoie": "XXXXXX",
            # Optional.
            "adrCpltDistribution": None,
            # Mandatory.
            # ref_insee_com_v1.csv
            "codeinseecom": "34172",
            # Mandatory.
            # FIXME referentiel?? => ask ASP
            "codepostalcedex": "34000",
        }

        # All mandatory.
        job_seeker_situation = {
            # ref_orienteur_v4.csv => does not include our data yet => ask ASP
            "orienteur": "01",
            # ref_niveau_formation_v3.csv
            # which field?? 00 is nowhere to be found.
            "niveauFormation": "00",
            "salarieEnEmploi": False,
            # ref_type_employeur_v3.csv
            # carefully match the rme_id of ref_mesure_v1.csv
            # Code 3352 : Le champ Type employeur doit être vide si le champ « En emploi » est à false
            # "salarieTypeEmployeur": "01",
            "salarieTypeEmployeur": None,
            # Code 3353 : Le champ Sans emploi depuis est obligatoire si le champ En emploi est à false
            # Code 3423 : Le code Durée sans emploi doit correspondre à une occurrence de la table ref_duree_allocation_emploi
            # ref_duree_allocation_emploi_v2.csv
            "salarieSansEmploiDepuis": "04",
            "salarieSansRessource": False,
            "inscritPoleEmploi": True,
            # ref_duree_allocation_emploi_v2.csv
            "inscritPoleEmploiDepuis": "04",
            "numeroIDE": "3500000A",
            "salarieRQTH": False,
            "salarieOETH": False,
            # If True then at least one of the 4 booleans above must be True.
            "salarieAideSociale": False,
            # OUI-M (oui majoré), OUI-NM (oui non majoré), NON.
            # FIXME OUI should be rejected.
            # Can be OUI-M/OUI-NM only if salarieAideSociale is True.
            "salarieBenefRSA": "NON",
            # ref_duree_allocation_emploi_v2.csv
            "salarieBenefRSADepuis": None,
            # Can be True only if salarieAideSociale is True.
            "salarieBenefASS": False,
            # ref_duree_allocation_emploi_v2.csv
            "salarieBenefASSDepuis": None,
            # Can be True only if salarieAideSociale is True.
            "salarieBenefAAH": False,
            # Code 3390 : Le champ Code Durée bénéficiaire de l'AAH depuis
            # est obligatoire si Bénéficiaire de l'AAH est à true
            # ref_duree_allocation_emploi_v2.csv
            "salarieBenefAAHDepuis": None,
            # Can be True only if salarieAideSociale is True.
            "salarieBenefATA": False,
            # ref_duree_allocation_emploi_v2.csv
            "salarieBenefATADepuis": None,
        }

        fiche_salarie = {
            "typeMouvement": "C",
            # FIXME AI and EITI are KO
            # ref_mesure_v3.csv
            "mesure": f"{siae.kind}_DC",
            # FIXME for user created siaes
            "siret": siae.siret,
            # Superfluous field, not expected by ASP system.
            # Is silently ignored by ASP system as expected.
            # We put it anyway because it will be needed with SSII softwares.
            # FIXME implement correct value.
            "numeroAnnexe": "ACI023201111A0M0",
            "personnePhysique": physical_person,
            "adresse": address,
            "situationSalarie": job_seeker_situation,
            "codeTraitement": None,
            "libelleTraitement": None,
        }

        # SIRET   DENOMINATION SOCIALE    ANNEXE1 ANNEXE2
        # 33055039301440  ITOUDEUX    AI 59L 20 9512 A0 M0    EI 59L 20 9512 A0 M0
        # 42366587601449  ITOUTROIS   EI 033 20 7523 A0 M0    ETTI 033 20 8541 A0 M0
        # 77562703701448  ITOUQUATRE  ETTI 087 20 3159 A0 M0  AI 087 20 7461 A0 M0
        # 80472537201448  ITOUCINQ    ACI 59L 20 7462 A0 M0   EI 59L 20 8541 A0 M0
        # 21590350101445  ITOUSIX ACI 033 20 7853 A0 M0   EI 033 20 8436 A0 M0
        # 41173709101444  ITOUSEPT    EI 087 20 9478 A0 M0    ACI 087 20 1248 A0 M0
        # 83533318801446  ITOUHUIT    ETTI 59L 20 1836 A0 M0  AI 59L 20 8471 A0 M0
        # 80847781401440  ITOUDIX AI 087 20 2486 A0 M0    ACI 087 20 3187 A0 M0
        # 78360196601442  ITOUUN  ACI 087 20 7432 A0 M0   AI 087 20 7432 A0 M0
        # 50829034301441  ITOUNEUF    ACI 033 20 3185 A0 M0   EI 033 20 6315 A0 M0

        # WARNING all AF above are valid but
        # EI 033 20 6315 A0 M0 and ACI 087 20 7432 A0 M0
        # (ITOUUN et ITOUNEUF)

        # Overwriting for tests.

        # KO - AI kind is rejected
        fiche_salarie["siret"] = "33055039301440"
        fiche_salarie["mesure"] = "AI_DC"

        # OK
        fiche_salarie["siret"] = "33055039301440"
        fiche_salarie["mesure"] = "EI_DC"

        return fiche_salarie

    def handle(self, dry_run=False, **options):
        self.set_logger(options.get("verbosity"))

        hirings_queryset = (
            JobApplication.objects.select_related("to_siae", "job_seeker", "approval")
            .prefetch_related("job_seeker__eligibility_diagnoses")
            .filter(
                state=JobApplicationWorkflow.STATE_ACCEPTED,
                to_siae__kind__in=Siae.ELIGIBILITY_REQUIRED_KINDS,
                to_siae__source=Siae.SOURCE_ASP,
                job_seeker__isnull=False,
                job_seeker__eligibility_diagnoses__isnull=False,
                approval__isnull=False,
            )
            # Prevent some hirings appearing twice in the queryset.
            .distinct()
        )

        all_hiring_ids = list(hirings_queryset.values_list("id", flat=True))

        sample_size = min(10, len(all_hiring_ids))

        hiring_ids = random.sample(all_hiring_ids, sample_size)
        assert len(hiring_ids) == sample_size

        hirings = hirings_queryset.filter(id__in=hiring_ids)
        assert hirings.count() == sample_size

        fiches_salarie = []
        row_number = 1
        for hiring in hirings:
            fiche_salarie = self.get_fiche_salarie_from_hiring(hiring)
            fiche_salarie["numLigne"] = row_number
            row_number += 1
            fiches_salarie.append(fiche_salarie)

        batch = {"msgInformatif": None, "telId": None, "lignesTelechargement": fiches_salarie}

        # RIAE_FS_AAAAMMJJHHMMSS as specified by the ASP.
        filename = f"RIAE_FS_{timezone.now().strftime('%Y%m%d%H%M%S')}.json"

        with open(f"exports/{filename}", "w") as f:
            f.write(json.dumps(batch))
            print(f"Wrote file {filename} to local exports dir.")

        # cat .ssh/known_hosts | grep valechange.asp-public.fr > .ssh/itou_asp_sftp_test.host_key
        # mkdir -p /app/exports/.ssh
        # docker cp ~/.ssh/itou_asp_sftp_test itou_django:/app/exports/.ssh
        # docker cp ~/.ssh/itou_asp_sftp_test.host_key itou_django:/app/exports/.ssh/known_hosts

        cnopts = pysftp.CnOpts()
        cnopts.hostkeys = None
        # cnopts.hostkeys.load("/app/exports/.ssh/known_hosts")
        with pysftp.Connection(
            host=settings.API_FS_SFTP_HOST,
            port=settings.API_FS_SFTP_PORT,
            username=settings.API_FS_SFTP_USER,
            private_key=settings.API_FS_SFTP_PRIVATE_KEY_PATH,
            cnopts=cnopts,
        ) as sftp:
            print(f"Current dir is {sftp.pwd}.")
            print(f"Dirs in current dir are {sftp.listdir()}.")
            with sftp.cd("depot"):
                try:
                    sftp.put(f"/app/exports/{filename}")
                except:
                    # Ignore cryptic error due to cryptic SFTP implementation on ASP side.
                    # FIXME catch specific exception.
                    pass
                print(f"Uploaded {filename} to depot.")
                print(f"Files present in depot dir: {sftp.listdir()}.")

            with sftp.cd("retrait"):
                print(f"Files present in retrait dir: {sftp.listdir()}.")
                for receipt in sftp.listdir():
                    sftp.get(receipt, localpath=f"exports/{receipt}")
                    sftp.remove(receipt)
                    print(f"Downloaded {receipt} to local and deleted it on server.")
                    with open(f"exports/{receipt}") as json_file:
                        data = json.load(json_file)
                        for row in data["lignesTelechargement"]:
                            print(f"Code {row['codeTraitement']} : " f"{row['libelleTraitement']}")

        # Responses encountered so far.

        # "codeTraitement": "0000",
        # "libelleTraitement": "La ligne de la fiche salarié a été enregistrée avec succès.",

        # "codeTraitement": "3436",
        # "libelleTraitement": "Un PASS IAE doit être unique pour un même SIRET",

        # => HAPPENS FOR AI !!
        # "codeTraitement": "3439",
        # "libelleTraitement": "La mesure ne fait pas partie de celles qui peuvent être intégrées via la plateforme",

        self.log("-" * 80)
        self.log("Done.")
