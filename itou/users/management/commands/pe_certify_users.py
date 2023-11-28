"""
This command uses the PE API to try and certify job seeker profiles against their
first name, last name, birthdate and NIR, eventually swapping first and last names
if needed.
"""

import logging

import tenacity
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from httpx import RequestError

from itou.users.enums import UserKind
from itou.users.models import JobSeekerProfile, User
from itou.utils.apis import pole_emploi_api_client
from itou.utils.apis.pole_emploi import (
    PoleEmploiAPIBadResponse,
    PoleEmploiAPIException,
    PoleEmploiRateLimitException,
)


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--wet-run", action="store_true", dest="wet_run")
        # default chunk size is chosen to be 200 so that the cron lasts about 3 minutes.
        parser.add_argument("--chunk-size", action="store", dest="chunk_size", default=200, type=int)

    def handle(self, wet_run, chunk_size, **options):
        pe_client = pole_emploi_api_client()

        @tenacity.retry(
            stop=tenacity.stop_after_attempt(10),
            wait=tenacity.wait_fixed(1),
            retry=tenacity.retry_if_exception_type(PoleEmploiRateLimitException),
        )
        def pe_check_user_details(user, swap=False):
            return pe_client.recherche_individu_certifie(
                user.first_name if not swap else user.last_name,
                user.last_name if not swap else user.first_name,
                user.birthdate,
                user.nir,
            )

        active_job_seekers = (
            User.objects.filter(
                kind=UserKind.JOB_SEEKER,
                is_active=True,
                jobseeker_profile__pe_last_certification_attempt_at=None,  # only those never seen yet. Retry someday?
                jobseeker_profile__pe_obfuscated_nir=None,
            )
            .select_related("jobseeker_profile")
            .order_by("-pk")
        )  # most recent users first, they are the top priority.
        self.stdout.write(f"> about to resolve first_name and last_name for count={active_job_seekers.count()} users.")

        eligible_users = active_job_seekers.exclude(Q(nir="") | Q(birthdate=None) | Q(first_name="") | Q(last_name=""))
        self.stdout.write(f"> only count={eligible_users.count()} users have the necessary data to be resolved.")

        examined_profiles = []
        certified_profiles = []
        swapped_users = []

        def certify_user(user, id_certifie):
            user.jobseeker_profile.pe_obfuscated_nir = id_certifie
            certified_profiles.append(user.jobseeker_profile)
            self.stdout.write(f"> certified user pk={user.pk} id_certifie={id_certifie}")

        for user in eligible_users[:chunk_size]:
            user.jobseeker_profile.pe_last_certification_attempt_at = timezone.now()
            examined_profiles.append(user.jobseeker_profile)
            try:
                response = pe_check_user_details(user)
            except (RequestError, PoleEmploiAPIException, PoleEmploiAPIBadResponse) as exc:
                self.stdout.write(f"! could not find a match for pk={user.pk} error={exc}")
                try:
                    response2 = pe_check_user_details(user, swap=True)
                except (RequestError, PoleEmploiAPIException, PoleEmploiAPIBadResponse) as exc:
                    self.stdout.write(
                        f"! no match found either for pk={user.pk} when swapping last and first names exc={exc}"
                    )
                else:
                    self.stdout.write(f"> SWAP DETECTED! user pk={user.pk} id_certifie={response2}")
                    user.last_name, user.first_name = user.first_name, user.last_name
                    certify_user(user, response2)
                    swapped_users.append(user)
            else:
                certify_user(user, response)

        if wet_run:
            self.stdout.write(f"> count={len(examined_profiles)} users have been examined.")

            JobSeekerProfile.objects.bulk_update(
                certified_profiles, ["pe_obfuscated_nir", "pe_last_certification_attempt_at"], batch_size=1000
            )
            self.stdout.write(f"> count={len(certified_profiles)} users have been certified.")

            not_certified = set(examined_profiles) - set(certified_profiles)
            JobSeekerProfile.objects.bulk_update(
                not_certified,
                ["pe_last_certification_attempt_at"],
                batch_size=1000,
            )
            self.stdout.write(f"> count={len(not_certified)} users could not be certified.")

            User.objects.bulk_update(swapped_users, ["first_name", "last_name"], batch_size=1000)
            self.stdout.write(f"> count={len(swapped_users)} users have been swapped.")
