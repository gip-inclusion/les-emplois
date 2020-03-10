import csv
import logging
import os

from django.core.management.base import BaseCommand

from itou.jobs.models import Appellation
from itou.siaes.models import Siae

CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

CSV_FILE = f"{CURRENT_DIR}/data/2019_07_liste_siae_additional_data.csv"

SEEN_SIRET = set()

WEBSITES_FIX = {
    "": "",
    "www.scop-espaces-verts.fr/": "http://www.scop-espaces-verts.fr",
    "www.aufildeleau.eu": "https://www.aufildeleau.eu",
    "www.lerelais.org": "https://www.lerelais.org",
    "www.arasc.fr": "https://www.arasc.fr",
    "www.utileco.alsace": "http://www.utileco.alsace",
    "www.servirplus.com": "http://www.servirplus.com",
    "http://www.asso-jade.fr/": "https://www.asso-jade.fr",
    "www.entraide-emploi.com/": "http://www.entraide-emploi.com",
    "www.brucheemploi.valleedelabruche.fr": "http://www.brucheemploi.valleedelabruche.fr",
    "http://www.espoir62.com/": "http://www.espoir62.com",
    "www.meinauservices.com": "https://www.meinauservices.com",
    "www.regiedesecrivains.com": "http://www.regiedesecrivains.com",
    "www.tremplins67-selestat.com": "http://www.tremplins67-selestat.com",
    "www.auportunes.com": "http://www.auportunes.com",
    "www.elsaunet.fr": "http://www.elsaunet.fr",
    "www.creno-services.fr": "https://www.creno-services.fr",
    "http://www.asso-lamarmite.org": "http://asso-lamarmite.org",
    "www.novea.fr": "https://www.novea.fr",
    "www.humanis.org": "https://www.humanis.org",
    "www.alemploi.fr/": "http://www.alemploi.fr",
    "www.emi67.fr": "https://www.emi67.fr",
    "www.emmaus-coupdemain.org": "https://www.emmaus-coupdemain.org",
    "www.apoin.fr": "https://www.apoin.fr",
    "www.asso-mobilex.org": "https://www.asso-mobilex.org",
    "www.industrieservice67.fr": "http://www.industrieservice67.fr",
    "www.laser-emploi.fr/germa": "http://laser-emploi.fr/antennes/germa-alsace/",
    "www.sistra.fr": "http://www.sistra.fr",
    "http://lepoles.org/": "http://lepoles.org",
    "www.scoprobat.fr": "https://www.scoprobat.fr",
    "http://etudesetchantiers.org/ile-de-France": "https://etudesetchantiers.org/ile-de-France",
    "http://www.regie2romainville.fr/": "",
    "www.envie.org": "https://www.envie.org",
    "www.groupeidees.fr/ideesinterim/": "http://www.groupeidees.fr/ideesinterim/",
    "http://www.capinterimfrance.fr": "https://www.capinterimfrance.fr",
    "www.sineo.fr/": "http://www.sineo.fr",
    "http://www.baluchon.fr": "http://baluchon.fr",
    "http://lepaysanurbain.fr/": "",
    "https://www.label-emmaus.co/": "https://www.label-emmaus.co",
    "www.fermesaintandre.com": "http://www.fermesaintandre.com",
    "http://www.vestali.fr/site/": "http://www.vestali.fr",
    "http://www.main-forte.fr/": "http://www.main-forte.fr",
    "http://www.chenelet.org": "https://www.chenelet.org",
    "http://www.horizonalimentaire.fr": "https://www.horizonalimentaire.fr",
    "http://www.lerelais.org": "https://www.lerelais.org",
    "https://www.asap-arras.fr/": "https://www.asap-arras.fr",
    "https://facebook.com/insertim.bruay": "https://facebook.com/insertim.bruay",
    "www.arsea.fr": "https://www.arsea.fr",
    "www.sava-association.com": "https://www.sava-association.com",
    "www.entraide-emploi.com": "http://www.entraide-emploi.com",
    "http://ovalie-interim.com/": "http://ovalie-interim.com",
    "www.ville-wissembourg.eu": "https://www.ville-wissembourg.eu",
    "www.libreobjet.com/fr/": "http://www.libreobjet.com",
    "http://cscvictorschoelcher.centres-sociaux.fr": "http://cscvictorschoelcher.centres-sociaux.fr",
    "www.emmaus-mundo.com": "https://emmaus-mundo.com",
    "www.horizonamitie.fr": "http://www.horizonamitie.fr",
    "www.vetis.org": "http://vetis.org",
    "www.emmaus-scherwiller.fr": "https://www.emmaus-scherwiller.fr",
    "http://www.lerelaisrestauration.com": "http://lerelaisrestauration.com",
    "http://www.groupeares.fr": "https://www.groupeares.fr",
    "http://www.ressourcerie-2mains.fr/": "http://www.ressourcerie-2mains.fr",
    "http://www.confiturerebelle.fr": "https://www.confiturerebelle.fr",
}


class Command(BaseCommand):
    """
    Import SIAE's additional data into the database.

    To debug:
        django-admin import_siae_additional_data --dry-run
        django-admin import_siae_additional_data --dry-run --verbosity=2

    To populate the database:
        django-admin import_siae_additional_data
    """

    help = "Import the content of the SIAE csv file into the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            dest="dry_run",
            action="store_true",
            help="Only print data to import",
        )

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

    def handle(self, dry_run=False, **options):

        self.set_logger(options.get("verbosity"))

        with open(CSV_FILE) as csvfile:

            # Count lines in CSV.
            reader = csv.reader(csvfile, delimiter=";")
            row_count = sum(1 for row in reader)
            last_progress = 0
            # Reset the iterator to iterate through the reader again.
            csvfile.seek(0)

            for i, row in enumerate(reader):

                if i == 0:
                    # Skip CSV header.
                    continue

                progress = int((100 * i) / row_count)
                if progress > last_progress + 5:
                    self.stdout.write(f"Creating SIAEs… {progress}%")
                    last_progress = progress

                self.logger.debug("-" * 80)

                siret = row[7]
                self.logger.debug(siret)
                assert len(siret) == 14
                if siret in SEEN_SIRET:
                    self.stderr.write(f"Siret already seen. Skipping {siret}.")
                    continue
                SEEN_SIRET.add(siret)

                # New info.

                website = row[9].strip()
                website = WEBSITES_FIX[website]
                self.logger.debug(website)

                appellations = []
                for j in range(10, 28, 2):
                    code_rome = row[j].strip()
                    if code_rome:
                        appellation_name = row[j + 1].strip()
                        self.logger.debug(appellation_name)
                        try:
                            appellation = (
                                Appellation.objects.filter(rome__pk=code_rome).filter(
                                    name__icontains=appellation_name
                                )
                            )[0]
                        except IndexError:
                            self.stderr.write(
                                f"Unknown appellation: `{appellation_name}`"
                            )
                        appellations.append(appellation)
                self.logger.debug(appellations)

                if not Siae.objects.filter(siret=siret).exists():
                    name = row[8]
                    department = row[1]
                    self.stderr.write(
                        f"Siret does not exist. Skipping department {department} - {siret} - {name}."
                    )
                    continue

                if not dry_run:
                    siae = Siae.objects.get(siret=siret)
                    siae.website = website
                    siae.save()
                    siae.jobs.add(*appellations)

        self.stdout.write("-" * 80)
        self.stdout.write("Done.")
