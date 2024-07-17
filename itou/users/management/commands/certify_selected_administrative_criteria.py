import datetime
import logging
from math import ceil

from django.db.models import Exists, OuterRef, Q
from django.utils.timezone import make_aware

from itou.eligibility.models.geiq import GEIQAdministrativeCriteria, GEIQSelectedAdministrativeCriteria
from itou.eligibility.models.iae import AdministrativeCriteria, SelectedAdministrativeCriteria
from itou.users.models import User
from itou.utils.apis import api_particulier
from itou.utils.command import BaseCommand
from itou.utils.iterators import chunks


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Certify selected administrative criteria from eligiility diagnosis made during the last 6 months
    by calling the Particulier API.
    """

    def add_arguments(self, parser):
        parser.add_argument("--limit", dest="limit", action="store", type=int)
        parser.add_argument("--verbose", dest="verbose", action="store_true")
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    def call_api_and_store_result(
        self,
        SelectedAdministrativeCriteriaModel,
        AdministrativeCriteriaModel,
        limit=None,
        verbose=False,
        wet_run=False,
    ):
        if not verbose:
            # Don't log HTTP requests detail.
            logging.getLogger("httpx").setLevel(logging.WARNING)
            logging.getLogger("httpcore").setLevel(logging.WARNING)

        total_criteria_with_certification = 0
        found_beneficiaries = set()
        found_not_beneficiaries = set()
        not_found_users = set()  # 404
        server_errors = 0  # 429, 503, 504

        criteria = AdministrativeCriteriaModel.objects.certifiable()
        period = (make_aware(datetime.datetime(2024, 1, 1)), make_aware(datetime.datetime(2024, 10, 1)))
        criteria_pks = (
            SelectedAdministrativeCriteriaModel.objects.filter(
                administrative_criteria__in=criteria,
                eligibility_diagnosis__created_at__range=period,
                eligibility_diagnosis__job_seeker__jobseeker_profile__birth_country__isnull=False,
                eligibility_diagnosis__job_seeker__jobseeker_profile__birthdate__isnull=False,
                eligibility_diagnosis__job_seeker__first_name__isnull=False,
                eligibility_diagnosis__job_seeker__last_name__isnull=False,
                eligibility_diagnosis__job_seeker__title__isnull=False,
            )
            .exclude(Q(certified__isnull=False) | Q(data_returned_by_api__error__contains="not_found"))  # exclude 404
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        if limit:
            criteria_pks = criteria_pks[:limit]

        total_criteria = len(criteria_pks)
        if total_criteria == 0:
            logger.info("No criteria to certify. Stop now and enjoy your day! ")
            return

        users_count = User.objects.filter(
            Exists(
                SelectedAdministrativeCriteria.objects.filter(
                    eligibility_diagnosis__job_seeker_id=OuterRef("pk"),
                    id__in=criteria_pks,
                )
            )
        ).count()
        logger.info(
            f"Candidats à certifier pour le modèle {SelectedAdministrativeCriteriaModel.__name__}: {users_count}"
        )

        chunks_total = ceil(total_criteria / 1000)
        chunks_count = 0
        for criteria_pk_subgroup in chunks(criteria_pks, 1000):
            criteria = SelectedAdministrativeCriteriaModel.objects.filter(pk__in=criteria_pk_subgroup).select_related(
                "administrative_criteria",
                "eligibility_diagnosis__job_seeker",
                "eligibility_diagnosis__job_seeker__jobseeker_profile",
                "eligibility_diagnosis__job_seeker__jobseeker_profile__birth_place",
                "eligibility_diagnosis__job_seeker__jobseeker_profile__birth_country",
            )

            with api_particulier.client() as client:
                for criterion in criteria:
                    criterion.certify(client, save=False)
                    data_returned_by_api = criterion.data_returned_by_api
                    if data_returned_by_api is None:
                        continue

                    if data_returned_by_api.get("status"):
                        total_criteria_with_certification += 1
                        if criterion.certified:
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

    def handle(self, limit, verbose, wet_run, *args, **kwargs):
        options = {"wet_run": wet_run, "limit": limit, "verbose": verbose}
        self.call_api_and_store_result(GEIQSelectedAdministrativeCriteria, GEIQAdministrativeCriteria, **options)
        self.call_api_and_store_result(SelectedAdministrativeCriteria, AdministrativeCriteria, **options)
