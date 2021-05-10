import logging
from datetime import date
from time import sleep

from django.core.management.base import BaseCommand

from itou.utils.apis.esd import get_access_token
from itou.utils.apis.pole_emploi import PoleEmploiIndividu, PoleEmploiRechercheIndividuCertifieAPI


class Command(BaseCommand):
    """
    Performs a sample HTTP request to pole emploi

    When ready:
        django-admin fetch_pole_emploi --verbosity=2
    """

    help = "Fetch sample user data stored by Pole Emploi"

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

    def fetch_user_info(self):
        individu_vide = PoleEmploiIndividu("LAURENT", "MARTIN", date(1979, 7, 25), "1800813800217")
        individu_baranes = PoleEmploiIndividu("Yolande", "Baranes", date(1957, 4, 19), "2570499351058")
        individu_maury = PoleEmploiIndividu("FREDERIC", "MAURY", date(1961, 1, 23), "1610133402024")
        individu_inexistant = PoleEmploiIndividu("AU CHOIX", "AU CHOIX", date(1980, 3, 2), "2800344109008")

        token = get_access_token("api_rechercheindividucertifiev1 rechercherIndividuCertifie")
        print(token)
        sleep(1)
        for individual_pole_emploi in [individu_vide, individu_baranes, individu_maury, individu_inexistant]:
            print(individual_pole_emploi.as_api_params())
            individual = PoleEmploiRechercheIndividuCertifieAPI(individual_pole_emploi, token)
            if individual.is_valid:
                print(individual.id_national_demandeur)
            else:
                print(f"Error while fetching individual: {individual.code_sortie}")
            sleep(1)

    def handle(self, dry_run=False, **options):
        self.set_logger(options.get("verbosity"))

        self.fetch_user_info()
        self.log("-" * 80)
        self.log("Done.")
