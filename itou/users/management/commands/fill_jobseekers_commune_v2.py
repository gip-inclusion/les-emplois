from django.contrib.postgres.search import TrigramSimilarity
from django.core.management.base import BaseCommand
from django.db.models import F

from itou.asp.models import CommuneV2, build_last_active_commune_v2_index
from itou.users.models import JobSeekerProfile


class Command(BaseCommand):
    help = "Matches CommuneV2 and Commune V2 for both fields in JobSeekerProfile and updates them"

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    def handle(self, *, wet_run, **options):
        last_active_commune_v2 = build_last_active_commune_v2_index()

        js_with_new_hexa_commune = []
        now_deactivated_communes = {}
        for js in JobSeekerProfile.objects.exclude(hexa_commune=None):
            new_commune = last_active_commune_v2.get(js.hexa_commune.code)
            if not new_commune:
                self.stdout.write(f"! COMMUNE DOES NOT EXIST ANYMORE {js.hexa_commune}\n")
            else:
                if new_commune.end_date:
                    self.stdout.write(f"! COMMUNE IS NOW DEACTIVATED {js.hexa_commune} {new_commune.end_date}\n")
                    now_deactivated_communes[js.hexa_commune.code] = js.hexa_commune
                    continue
                js.hexa_commune_v2 = new_commune
                js_with_new_hexa_commune.append(js)

        for code, commune in now_deactivated_communes.items():
            resolved_v2 = (
                CommuneV2.objects.exclude(code=code)
                .annotate(similarity=TrigramSimilarity("name", commune.name))
                .filter(
                    end_date=None,  # only cities that still "exist"
                    code__startswith=commune.code[:2],
                    similarity__gte=0.4,
                )
                .order_by(F("end_date").asc(nulls_last=True))
                .last()
            )
            if resolved_v2:
                for js in commune.jobseekerprofile_set.all():
                    js.hexa_commune_v2 = resolved_v2
                    js_with_new_hexa_commune.append(js)
            else:
                self.stdout.write(f"!!! NO MATCH : PLEASE MANUALLY RESOLVE COMMUNE {commune}\n")

        js_with_new_birth_place = []
        for js in JobSeekerProfile.objects.exclude(birth_place=None):
            new_birth_place = last_active_commune_v2.get(js.birth_place.code)
            if not new_birth_place:
                self.stdout.write(f"! BIRTH PLACE DOES NOT EXIST ANYMORE {js.birth_place}\n")
            else:
                js.birth_place_v2 = new_birth_place
                js_with_new_birth_place.append(js)
            js_with_new_birth_place.append(js)

        if wet_run:
            n_objs = JobSeekerProfile.objects.bulk_update(
                js_with_new_hexa_commune, fields=["hexa_commune_v2"], batch_size=1000
            )
            self.stdout.write(f"> successfully updated count={n_objs} hexa_commune_v2")

            n_objs = JobSeekerProfile.objects.bulk_update(
                js_with_new_birth_place, fields=["birth_place_v2"], batch_size=1000
            )
            self.stdout.write(f"> successfully updated count={n_objs} birth_place_v2")
