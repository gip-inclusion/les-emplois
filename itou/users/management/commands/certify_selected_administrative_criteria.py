import concurrent
import logging
from math import ceil

from dateutil.relativedelta import relativedelta
from django.db.models import Q
from django.utils import timezone

from itou.eligibility.models.geiq import GEIQAdministrativeCriteria, GEIQSelectedAdministrativeCriteria
from itou.eligibility.models.iae import AdministrativeCriteria, SelectedAdministrativeCriteria
from itou.users.models import User
from itou.utils.command import BaseCommand
from itou.utils.iterators import chunks


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Certify selected administrative criteria from eligiility diagnosis made during the last 6 months
    by calling the Particulier API."""

    def add_arguments(self, parser):
        parser.add_argument("--limit", dest="limit", action="store", type=int)
        parser.add_argument("--synchronously", dest="synchronously", action="store_true")
        parser.add_argument("--verbose", dest="verbose", action="store_true")
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    def call_api_and_store_result(
        self,
        SelectedAdministrativeCriteriaModel,
        AdministrativeCriteriaModel,
        limit=None,
        synchronously=False,
        verbose=False,
        wet_run=False,
    ):
        if not verbose:
            # Don't log HTTP requests detail.
            logging.getLogger("httpx").setLevel(logging.WARNING)
            logging.getLogger("httpcore").setLevel(logging.WARNING)

        total_criteria = 0
        total_criteria_with_certification = 0
        found_beneficiaries = set()
        found_not_beneficiaries = set()
        not_found_users = set()  # 404
        server_errors = 0  # 429, 503, 504

        criteria = AdministrativeCriteriaModel.objects.certifiable()
        six_months = timezone.now() - relativedelta(months=6)
        criteria_pks_qs = (
            SelectedAdministrativeCriteriaModel.objects.filter(
                administrative_criteria__in=criteria,
                eligibility_diagnosis__created_at__gte=six_months,
                eligibility_diagnosis__job_seeker__jobseeker_profile__birth_country__isnull=False,
                eligibility_diagnosis__job_seeker__jobseeker_profile__birthdate__isnull=False,
                eligibility_diagnosis__job_seeker__first_name__isnull=False,
                eligibility_diagnosis__job_seeker__last_name__isnull=False,
                eligibility_diagnosis__job_seeker__title__isnull=False,
            )
            .exclude(Q(certified__isnull=False) | Q(data_returned_by_api__error__contains="not_found"))  # exclude 404
            .values("pk", "eligibility_diagnosis__job_seeker__pk")
        )
        if limit:
            criteria_pks_qs = criteria_pks_qs[:limit]
        criteria_pks = list([val["pk"] for val in criteria_pks_qs])

        total_criteria += len(criteria_pks)

        # It should be better to get the User from criteria_pks but I didn't manage to make it work.
        # I tried the following:
        # User.objects.filter(eligibility_diagnoses__administrativecriteria_set__in=criteria_pks)
        users_pks = set([val["eligibility_diagnosis__job_seeker__pk"] for val in criteria_pks_qs])
        users_count = User.objects.filter(pk__in=users_pks).count()
        logger.info(f"Candidats à certifier pour le modèle {SelectedAdministrativeCriteriaModel}: {users_count}")

        chunks_total = ceil(total_criteria / 1000)
        chunks_count = 0
        for criteria_pk_subgroup in chunks(criteria_pks, 1000):
            criteria = (
                SelectedAdministrativeCriteriaModel.objects.filter(pk__in=criteria_pk_subgroup)
                .select_related(
                    "eligibility_diagnosis__job_seeker__jobseeker_profile",
                    "eligibility_diagnosis__job_seeker",
                    "eligibility_diagnosis__job_seeker__jobseeker_profile__birth_place",
                    "eligibility_diagnosis__job_seeker__jobseeker_profile__birth_country",
                )
                .all()
            )

            # Tenacity's retry feature does not seem to work with ThreadPoolExecutor.
            # httpx.RequestError, which should retry, does not.
            # So leave the possibility to certify more criteria even if it lasts longer.
            if synchronously:
                for criterion in criteria:
                    criterion.certify(save=False)
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                    batch_futures = []
                    for criterion in criteria:
                        batch_futures.append(executor.submit(criterion.certify, False))
                    _done, _not_done = concurrent.futures.wait(batch_futures, timeout=3600)

            for criterion in criteria:
                data_returned_by_api = criterion.data_returned_by_api
                # 429, 503 and 504
                # See api_particulier.py
                if type(criterion.data_returned_by_api) is not dict:
                    data_returned_by_api = {"error": criterion.data_returned_by_api}

                if data_returned_by_api.get("status"):
                    total_criteria_with_certification += 1
                    if data_returned_by_api["status"] == "beneficiaire":
                        found_beneficiaries.add(criterion.eligibility_diagnosis.job_seeker.pk)
                    else:
                        found_not_beneficiaries.add(criterion.eligibility_diagnosis.job_seeker.pk)

                if data_returned_by_api.get("error"):
                    if data_returned_by_api["error"] == "not_found":
                        not_found_users.add(criterion.eligibility_diagnosis.job_seeker.pk)
                    else:
                        server_errors += 1

            if wet_run:
                SelectedAdministrativeCriteriaModel.objects.bulk_update(
                    criteria,
                    fields=[
                        "data_returned_by_api",
                        "certified",
                        "certification_period",
                        "certified_at",
                    ],
                )

            chunks_count += 1
            logger.info(f"########### {chunks_count/chunks_total*100:.2f}%")

        logger.info(f"Total criteria to be certified: {total_criteria}")
        logger.info(f"Total criteria with certification: {total_criteria_with_certification}")
        logger.info(f"Not beneficiaries: {len(found_not_beneficiaries)}")
        logger.info(f"Beneficiaries: {len(found_beneficiaries)}")
        logger.info(f"Not found: {len(not_found_users)}")
        logger.info(f"Server errors: {server_errors}")
        users_found = total_criteria_with_certification / total_criteria * 100
        logger.info(f"That's {users_found:.2f}% users found.")

    def handle(self, limit, synchronously, verbose, wet_run, *args, **kwargs):
        options = {"wet_run": wet_run, "limit": limit, "synchronously": synchronously, "verbose": verbose}
        self.call_api_and_store_result(GEIQSelectedAdministrativeCriteria, GEIQAdministrativeCriteria, **options)
        self.call_api_and_store_result(SelectedAdministrativeCriteria, AdministrativeCriteria, **options)
