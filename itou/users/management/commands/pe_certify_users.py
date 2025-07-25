"""
This command uses the PE API to try and certify job seeker profiles against their
first name, last name, birthdate and NIR, eventually swapping first and last names
if needed.
"""

import datetime

import tenacity
from django.db.models import F, Q
from django.utils import timezone
from httpx import RequestError

from itou.users.enums import IdentityCertificationAuthorities, UserKind
from itou.users.models import IdentityCertification, JobSeekerProfile, User
from itou.utils.apis import pole_emploi_partenaire_api_client
from itou.utils.apis.pole_emploi import (
    PoleEmploiAPIBadResponse,
    PoleEmploiAPIException,
    PoleEmploiRateLimitException,
)
from itou.utils.command import BaseCommand, dry_runnable


RETRY_DELAY = datetime.timedelta(days=7)


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--wet-run", action="store_true", dest="wet_run")
        # default chunk size is chosen to be 200 so that the cron lasts about 3 minutes.
        parser.add_argument("--chunk-size", action="store", dest="chunk_size", default=200, type=int)

    @dry_runnable
    def handle(self, chunk_size, **options):
        pe_client = pole_emploi_partenaire_api_client()

        @tenacity.retry(
            stop=tenacity.stop_after_attempt(10),
            wait=tenacity.wait_fixed(1),
            retry=tenacity.retry_if_exception_type(PoleEmploiRateLimitException),
        )
        def pe_check_user_details(user, swap=False):
            return pe_client.recherche_individu_certifie(
                user.first_name if not swap else user.last_name,
                user.last_name if not swap else user.first_name,
                user.jobseeker_profile.birthdate,
                user.jobseeker_profile.nir,
            )

        active_job_seekers = (
            User.objects.filter(
                kind=UserKind.JOB_SEEKER,
                is_active=True,
                jobseeker_profile__pe_obfuscated_nir=None,
            )
            .exclude(jobseeker_profile__pe_last_certification_attempt_at__gt=timezone.now() - RETRY_DELAY)
            .select_related("jobseeker_profile")
        )
        self.logger.info("about to resolve first_name and last_name for count=%d users", active_job_seekers.count())

        eligible_users = active_job_seekers.exclude(
            Q(jobseeker_profile__nir="") | Q(jobseeker_profile__birthdate=None) | Q(first_name="") | Q(last_name="")
        )
        self.logger.info("only count=%d users have the necessary data to be resolved", eligible_users.count())

        examined_profiles = []
        certified_profiles = []
        identity_certifications = []
        swapped_users = []

        def certify_user(user, id_certifie):
            user.jobseeker_profile.pe_obfuscated_nir = id_certifie
            identity_certifications.append(
                IdentityCertification(
                    certifier=IdentityCertificationAuthorities.API_FT_RECHERCHE_INDIVIDU_CERTIFIE,
                    jobseeker_profile=user.jobseeker_profile,
                    certified_at=timezone.now(),
                )
            )
            certified_profiles.append(user.jobseeker_profile)
            self.logger.info("certified user pk=%d", user.pk)

        for user in eligible_users.order_by(
            F("jobseeker_profile__pe_last_certification_attempt_at").asc(nulls_first=True)
        )[:chunk_size]:
            user.jobseeker_profile.pe_last_certification_attempt_at = timezone.now()
            examined_profiles.append(user.jobseeker_profile)
            try:
                response = pe_check_user_details(user)
            except (RequestError, PoleEmploiAPIException, PoleEmploiAPIBadResponse) as exc:
                self.logger.warning(f"could not find a match for pk={user.pk} error={exc}")
                try:
                    response2 = pe_check_user_details(user, swap=True)
                except (RequestError, PoleEmploiAPIException, PoleEmploiAPIBadResponse) as exc:
                    self.logger.warning(
                        f"no match found either for pk={user.pk} when swapping last and first names exc={exc}"
                    )
                else:
                    self.logger.info("SWAP DETECTED: user pk=%d", user.pk)
                    user.last_name, user.first_name = user.first_name, user.last_name
                    certify_user(user, response2)
                    swapped_users.append(user)
            else:
                certify_user(user, response)

        self.logger.info("count=%d users have been examined.", len(examined_profiles))

        JobSeekerProfile.objects.bulk_update(
            certified_profiles,
            [
                "pe_obfuscated_nir",
                "pe_last_certification_attempt_at",
            ],
            batch_size=1000,
        )
        self.logger.info("count=%d users have been certified", len(certified_profiles))
        IdentityCertification.objects.upsert_certifications(identity_certifications)
        self.logger.info("count=%d identity certifications recorded.", len(identity_certifications))

        not_certified = set(examined_profiles) - set(certified_profiles)
        JobSeekerProfile.objects.bulk_update(
            not_certified,
            ["pe_last_certification_attempt_at"],
            batch_size=1000,
        )
        self.logger.info("count=%d users could not be certified.", len(not_certified))

        User.objects.bulk_update(swapped_users, ["first_name", "last_name"], batch_size=1000)
        self.logger.info("count=%d users have been swapped", len(swapped_users))
