import datetime
import time

from django.db import transaction

from itou.cities.models import City
from itou.companies.enums import POLE_EMPLOI_SIRET, ContractType, JobSource, JobSourceTag
from itou.companies.models import Company, JobDescription
from itou.jobs.models import Appellation
from itou.utils.apis import pe_api_enums, pole_emploi_partenaire_api_client
from itou.utils.command import BaseCommand
from itou.utils.sync import DiffItemKind, yield_sync_diff


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
    "DDT": ContractType.FIXED_TERM_TREMPLIN,
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


def pe_offer_to_job_description(data, logger):
    source_id = data["id"]
    rome_code = data["romeCode"]
    appellation_label = data["appellationlibelle"]
    appellation = Appellation.objects.filter(name=appellation_label, rome__code=rome_code).first()
    if appellation is None:
        appellation = Appellation.objects.autocomplete(search_string=appellation_label, rome_code=rome_code).first()
        if appellation is None:
            logger.warning(f"no appellation match found ({rome_code=} {appellation_label=}) skipping {source_id=}")
            return None

    if "codePostal" not in data["lieuTravail"]:
        logger.warning(f"no zipcode in raw offer, skipping {source_id=}")
        return None

    source_url = data.get("origineOffre", {}).get("urlOrigine")
    if not source_url:
        logger.warning(f"no job URL in raw offer, skipping {source_id=}")
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
    source_tags = []
    if data["natureContrat"] == pe_api_enums.NATURE_CONTRATS[pe_api_enums.NATURE_CONTRAT_PEC]:
        source_tags.append(JobSourceTag.FT_PEC_OFFER.value)
    if data["entrepriseAdaptee"]:
        source_tags.append(JobSourceTag.FT_EA_OFFER.value)
    if not source_tags:
        # Hopefully this will never happen, but if it does, we want to know about it.
        raise ValueError(f"Unexpected {data['natureContrat']=} {data['entrepriseAdaptee']=} for offer {data['id']=}")
    return JobDescription(
        appellation=appellation,
        created_at=data["dateCreation"],  # from iso8601
        # dateActualisation does not seem to be optional but apparently it is not always set...
        # In such case, fallbacking to dateCreation seems reasonable.
        updated_at=data.get("dateActualisation", data["dateCreation"]),  # same
        custom_name=data["intitule"],
        description=data["description"],
        contract_type=PE_TYPE_TO_CONTRACT_TYPE[data["typeContrat"]],
        other_contract_type=data["typeContratLibelle"],
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
        source_tags=source_tags,
        source_url=source_url,
    )


class Command(BaseCommand):
    help = "Synchronizes the list of PEC offers from FT"

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")
        parser.add_argument("--delay", action="store", dest="delay", default=1, type=int, choices=range(0, 5))

    def handle(self, *, wet_run, delay, **options):
        pe_client = pole_emploi_partenaire_api_client()
        pe_siae = Company.unfiltered_objects.get(siret=POLE_EMPLOI_SIRET)

        # NOTE: using this unfiltered API we can only sync at most 1149 PEC offers. If someday there are more offers,
        # we will need to setup a much more complicated sync mechanism, for instance by requesting every department one
        # by one. But so far we are not even close from half this quota.
        raw_pec_offers = pe_client.retrieve_all_offres(
            natureContrat=pe_api_enums.NATURE_CONTRAT_PEC,
            delay_between_requests=datetime.timedelta(seconds=delay),
        )
        self.logger.info(f"retrieved count={len(raw_pec_offers)} PEC offers from FT API")
        time.sleep(delay)
        raw_ea_offers = pe_client.retrieve_all_offres(
            entreprisesAdaptees=True,
            delay_between_requests=datetime.timedelta(seconds=delay),
        )
        self.logger.info(f"retrieved count={len(raw_ea_offers)} EA offers from FT API")

        # Merge the 2 lists, to handle the improbable case where a PEC offer comes from an EA company.
        raw_offers = list(
            (
                {offer["id"]: offer for offer in raw_pec_offers} | {offer["id"]: offer for offer in raw_ea_offers}
            ).values()
        )
        self.logger.info(f"retrieved count={len(raw_offers)} unique offers from FT API")

        added_offers = []
        updated_offers = []
        offers_to_remove = set()

        with transaction.atomic():
            # get the weakest possible lock on these rows, as we don't want to block the entire system
            # but still avoid creating concurrent rows in the same time while we inspect their keys
            pe_offers = JobDescription.objects.filter(source_kind=JobSource.PE_API).select_for_update(
                of=["self"], skip_locked=True, no_key=True
            )
            for item in yield_sync_diff(raw_offers, "id", pe_offers, "source_id", []):
                if item.kind in [DiffItemKind.ADDITION, DiffItemKind.EDITION]:
                    job = pe_offer_to_job_description(item.raw, self.logger)
                    if job:
                        job.company = pe_siae
                        if item.kind == DiffItemKind.ADDITION:
                            added_offers.append(job)
                        else:
                            job.pk = item.db_obj.pk
                            updated_offers.append(job)
                elif item.kind == DiffItemKind.DELETION:
                    offers_to_remove.add(item.key)

            if wet_run:
                objs = JobDescription.objects.bulk_create(added_offers)
                self.logger.info("successfully created count=%d PE job offers", len(objs))
                n_objs = JobDescription.objects.bulk_update(
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
                self.logger.info("successfully updated count=%d PE job offers", n_objs)
                # Do not deactivate: for now it's not very relevant to keep objects that we
                # are not the source or master of. We'll see if that makes sense on the analytics
                # side someday, but remove them entirely for now.
                n_objs, _ = JobDescription.objects.filter(
                    source_kind=JobSource.PE_API, source_id__in=offers_to_remove
                ).delete()
                self.logger.info("successfully deleted count=%d PE job offers", n_objs)
