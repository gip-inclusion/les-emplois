from time import sleep

from django.core.management.base import BaseCommand
from django.db import transaction

from itou.cities.models import City
from itou.companies.enums import POLE_EMPLOI_SIRET, ContractNature, ContractType, JobSource
from itou.companies.models import Siae, SiaeJobDescription
from itou.jobs.models import Appellation
from itou.utils.apis import pe_api_enums, pole_emploi_api_client
from itou.utils.sync import DiffItemKind, yield_sync_diff


# Source:
# https://pole-emploi.io/data/api/offres-emploi?tabgroup-api=documentation&doc-section=api-doc-section-rechercher-par-crit%C3%A8res
OFFERS_MIN_INDEX = 0
OFFERS_MAX_INDEX = 1149
OFFERS_MAX_RANGE = 150

PE_TYPE_TO_CONTRACT_TYPE = {
    "CDI": ContractType.PERMANENT,
    "CDD": ContractType.FIXED_TERM,
    "MIS": ContractType.TEMPORARY,
    "SAI": ContractType.OTHER,
    "CCE": ContractType.OTHER,
    "FRA": ContractType.OTHER,
    "LIB": ContractType.OTHER,
    "REP": ContractType.OTHER,
    "TTI": ContractType.TEMPORARY,
    "DDI": ContractType.FIXED_TERM_I,
    "DIN": ContractType.PERMANENT,
}


class NoAppellationFoundException(Exception):
    def __init__(self, rome_code, label):
        self.rome_code = rome_code
        self.label = label

    def __str__(self):
        return f"NoAppellationFound(rome={self.rome_code},label='{self.label}')"


class NoZipCodeException(Exception):
    pass


def pe_offer_to_job_description(data):
    source_id = data["id"]
    rome_code = data["romeCode"]
    appellation_label = data["appellationlibelle"]
    appellation = Appellation.objects.filter(name=appellation_label, rome__code=rome_code).first()
    if appellation is None:
        appellation = Appellation.objects.autocomplete(search_string=appellation_label, rome_code=rome_code).first()
        if appellation is None:
            print(f"! no appellation match found ({rome_code=} {appellation_label=}) skipping {source_id=}")
            return None

    if "codePostal" not in data["lieuTravail"]:
        print(f"! no zipcode in raw offer, skipping {source_id=}")
        return None

    source_url = data.get("origineOffre", {}).get("urlOrigine")
    if not source_url:
        print(f"! no job URL in raw offer, skipping {source_id=}")
        return None

    code_postal = int(data["lieuTravail"]["codePostal"])
    # FIXME(vperron): This makes the PEC jobs have a less accurate position on our site than they had before.
    # This should and could be removed as soon as the cities sync project has been completed.
    if 75001 <= code_postal <= 75020:
        city = City.objects.get(code_insee="75056")
    elif 69001 <= code_postal <= 69009:
        city = City.objects.get(code_insee="69123")
    elif 13001 <= code_postal <= 13016:
        city = City.objects.get(code_insee="13055")
    else:
        city = City.objects.get(code_insee=data["lieuTravail"]["commune"])
    return SiaeJobDescription(
        appellation=appellation,
        created_at=data["dateCreation"],  # from iso8601
        updated_at=data["dateActualisation"],  # same
        custom_name=data["intitule"],
        description=data["description"],
        contract_type=PE_TYPE_TO_CONTRACT_TYPE[data["typeContrat"]],
        other_contract_type=data["typeContratLibelle"],
        contract_nature=ContractNature.PEC_OFFER,
        location=city,
        # There is no real way to retrieve this information. We could try a regexp-based parsing
        # but it would be error prone and inaccurate.
        hours_per_week=None,
        open_positions=data.get("nombrePostes"),  # might be None
        profile_description=data.get("experienceLibelle"),  # same
        # This is a little abusive but I rather use an existing (very much unused at time of writing) field
        # that already exists on the model to store a simple information, than add a complex JSON field or a dedicated
        # field just for the PE specific need.
        market_context_description=data.get("entreprise", {}).get("nom", ""),
        source_id=data["id"],
        source_kind=JobSource.PE_API,
        source_url=source_url,
    )


class Command(BaseCommand):
    help = "Synchronizes the list of PEC offers on a daily basis"

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")
        parser.add_argument("--delay", action="store", dest="delay", default=1, type=int, choices=range(0, 5))

    def handle(self, *, wet_run, delay, **options):
        pe_client = pole_emploi_api_client()
        pe_siae = Siae.unfiltered_objects.get(siret=POLE_EMPLOI_SIRET)

        # NOTE: using this unfiltered API we can only sync at most 1149 PEC offers. If someday there are more offers,
        # we will need to setup a much more complicated sync mechanism, for instance by requesting every department one
        # by one. But so far we are not even close from half this quota.
        raw_offers = []
        for i in range(OFFERS_MIN_INDEX, OFFERS_MAX_INDEX, OFFERS_MAX_RANGE):
            max_range = min(OFFERS_MAX_INDEX, i + OFFERS_MAX_RANGE - 1)
            offers = pe_client.offres(natureContrat=pe_api_enums.NATURE_CONTRAT_PEC, range=f"{i}-{max_range}")
            self.stdout.write(f"retrieved count={len(offers)} PEC offers from PE API")
            if not offers:
                break
            raw_offers.extend(offers)

            sleep(delay)

        added_offers = []
        updated_offers = []
        offers_to_remove = set()

        with transaction.atomic():
            # get the weakest possible lock on these rows, as we don't want to block the entire system
            # but still avoid creating concurrent rows in the same time while we inspect their keys
            pe_offers = SiaeJobDescription.objects.filter(source_kind=JobSource.PE_API).select_for_update(
                of=["self"], skip_locked=True, no_key=True
            )
            for item in yield_sync_diff(raw_offers, "id", pe_offers, "source_id", []):
                if item.kind in [DiffItemKind.ADDITION, DiffItemKind.EDITION]:
                    job = pe_offer_to_job_description(item.raw)
                    if job:
                        job.siae = pe_siae
                        if item.kind == DiffItemKind.ADDITION:
                            added_offers.append(job)
                        else:
                            job.pk = item.db_obj.pk
                            updated_offers.append(job)
                elif item.kind == DiffItemKind.DELETION:
                    offers_to_remove.add(item.key)

            if wet_run:
                objs = SiaeJobDescription.objects.bulk_create(added_offers)
                self.stdout.write(f"> successfully created count={len(objs)} PE job offers")
                n_objs = SiaeJobDescription.objects.bulk_update(
                    updated_offers,
                    fields=[
                        "appellation",
                        "created_at",
                        "updated_at",
                        "custom_name",
                        "description",
                        "contract_type",
                        "other_contract_type",
                        "location",
                        "open_positions",
                        "profile_description",
                        "market_context_description",
                        "source_url",
                    ],
                )
                self.stdout.write(f"> successfully updated count={n_objs} PE job offers")
                # Do not deactivate: for now it's not very relevant to keep objects that we
                # are not the source or master of. We'll see if that makes sense on the analytics
                # side someday, but remove them entirely for now.
                n_objs, _ = SiaeJobDescription.objects.filter(
                    source_kind=JobSource.PE_API, source_id__in=offers_to_remove
                ).delete()
                self.stdout.write(f"> successfully deleted count={n_objs} PE job offers")
