from django.core.management.base import BaseCommand

from itou.asp.models import Commune, build_last_active_commune_v2_index
from itou.users.models import JobSeekerProfile


MANUAL_MAPPING = {
    "14296": "14658",  # GAST -> Noues de Sienne
    "14372": "14143",  # LIVRY -> Caumont-sur-Aure
    "14722": "14143",  # VACQUERIE -> Caumont-sur-Aure
    "16376": "16192",  # SURIS -> Terres-de-Haute-Charente
    "22270": "22093",  # SAINT-AARON/LAMBALLE -> Lamballe
    "24089": "24325",  # CAZOULES -> Pechs-de-l'Espérance
    "28356": "28012",  # SAINT-PELLERIN -> Arrou
    "44017": "44180",  # BONNOEUVRE -> Vallons-de-l'Erdre
    "54342": "54099",  # MANCIEULLES -> Val de Briey
    "61083": "61474",  # CHAMBOIS -> Gouffern en Auge
    "74093": "74010",  # CRAN-GEVRIER -> Annecy
    "74204": "74282",  # OLLIERES -> Fillière
    "74217": "74010",  # PRINGY -> Annecy
    "74245": "74282",  # SAINT-MARTIN-BELLEVUE -> Fillière
    "85048": "85302",  # CHAMBRETAUD -> Chanverrie
}


class Command(BaseCommand):
    help = "Manually resolves disappeared communes in jobseeker profiles"

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    def handle(self, *, wet_run, **options):
        last_active_commune_v2 = build_last_active_commune_v2_index()

        js_with_new_hexa_commune = []
        for before, after in MANUAL_MAPPING.items():
            communes = Commune.objects.filter(code=before)
            commune_v2 = last_active_commune_v2.get(after)
            for commune in communes:
                for js in commune.jobseekerprofile_set.all():
                    js.hexa_commune_v2 = commune_v2
                    js_with_new_hexa_commune.append(js)

        if wet_run:
            n_objs = JobSeekerProfile.objects.bulk_update(
                js_with_new_hexa_commune, fields=["hexa_commune_v2"], batch_size=1000
            )
            self.stdout.write(f"> successfully updated count={n_objs} hexa_commune_v2")
