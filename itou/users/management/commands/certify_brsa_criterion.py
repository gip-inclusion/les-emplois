import time
from math import ceil

import httpx
import tenacity
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db.models import F
from django.utils import timezone
from django.utils.http import urlencode

from itou.eligibility.models.iae import AdministrativeCriteria
from itou.users.models import User
from itou.utils.command import BaseCommand
from itou.utils.iterators import chunks
from itou.utils.logging import logger


class Command(BaseCommand):
    """Certify BRSA criteria calling the /revenu-solidarite-active API particulier endpoint.
    Conclusions after a first run on 15105 users:
    - Performed in 23747.56s (about 7h).
    - Found (200): 12590
    - Not found (404): 2330
    - That's 83.35%.
    - Server errors (503): 183

    TODO:
    - on not found users, check jobseeker_profile.pe_obfuscated_nir
      and jobseeker_profile.pe_last_certification_attempt_at
    - store the BRSA result.
    """

    def handle(self, *args, **kwargs):
        # RSA
        criteria = AdministrativeCriteria.objects.get(pk=1)
        six_months = timezone.now() - relativedelta(months=6)
        users_pks = (
            User.objects.filter(
                eligibility_diagnoses__administrative_criteria=criteria,
                jobseeker_profile__birth_place__isnull=False,
                eligibility_diagnoses__created_at__gte=six_months,
            )
            .distinct()
            .values_list("pk", flat=True)
        )
        total_users = len(users_pks)
        chunks_total = ceil(total_users / 1000)

        done = 0
        found_users = 0
        not_found_users = 0
        server_errors = []

        class ApiParticulierClient:
            def __init__(self):
                self.client = httpx.Client(headers={"X-Api-Key": settings.API_PARTICULIERS_TOKEN})

        # response = ApiParticulierClient().client.get("https://particulier.api.gouv.fr/api/introspect")
        # response = response.json()
        # code = response.status_code

        @tenacity.retry(
            wait=tenacity.wait_fixed(2),
            stop=tenacity.stop_after_attempt(4),
            retry=tenacity.retry_if_exception_type(httpx.RequestError),
        )
        def call_api_particuliers(data):
            # https://particulier.api.gouv.fr/api/v2/revenu-solidarite-active?nomNaissance=KHIRI&prenoms%5B%5D=K%C3%A9VIN&prenoms%5B%5D=anthony&anneeDateDeNaissance=1994&moisDateDeNaissance=2&jourDateDeNaissance=14&codeInseeLieuDeNaissance=75214&codePaysLieuDeNaissance=99100&sexe=M
            params = {
                "nomNaissance": data.get("last_name"),
                "prenoms[]": data.get("first_name").split(" "),
                "anneeDateDeNaissance": data.get("birth_year"),
                "moisDateDeNaissance": data.get("birth_month"),
                "jourDateDeNaissance": data.get("birth_day"),
                "codeInseeLieuDeNaissance": data.get("birth_place_code"),
                "codePaysLieuDeNaissance": data.get("birth_country_code"),
                "sexe": data.get("gender"),
            }
            complete_url = f"https://particulier.api.gouv.fr/api/v2/revenu-solidarite-active?{urlencode(params, True)}"
            response = ApiParticulierClient().client.get(complete_url)
            if response.status_code == 503:
                raise httpx.RequestError(message=complete_url)
            return response

        start = time.perf_counter()
        chunks_count = 0
        for users_pk in chunks(users_pks, 1000):
            users = (
                User.objects.filter(pk__in=users_pk)
                .values(
                    "first_name",
                    "last_name",
                    "birthdate",
                    "title",
                )
                .annotate(country=F("jobseeker_profile__birth_country__code"))
                .annotate(city=F("jobseeker_profile__birth_place__code"))
            )

            for user in users:
                data = {
                    "first_name": user["first_name"],
                    "last_name": user["last_name"],
                    "birth_year": user["birthdate"].year,
                    "birth_month": user["birthdate"].month,
                    "birth_day": user["birthdate"].day,
                    "birth_place_code": user["city"],
                    "birth_country_code": f"99{user['country']}" if user["country"] else "",
                }
                gender = None
                match user["title"]:
                    case "MME":
                        gender = "F"
                    case "M":
                        gender = "M"
                    case "":
                        logger.error("No gender")
                data["gender"] = gender

                response = None
                try:
                    response = call_api_particuliers(data=data)
                    match response.status_code:
                        case 200:
                            found_users += 1
                        case 404:
                            not_found_users += 1
                        # 503 error strikes a RetryError.
                        case (502, 501, 500):
                            server_errors(response.request.url)
                            server_errors.append(response.json()["reason"])
                            logger.info(response.json()["reason"])
                except tenacity.RetryError as retry_err:
                    ex = str(retry_err.last_attempt._exception)
                    server_errors.append(ex)
                done += 1
                print(f"## {done}/{total_users}")

            chunks_count += 1

            print(f"########### {chunks_count/chunks_total*100:.2f}%", end="\r")

        elapsed = time.perf_counter() - start
        logger.info(f"Performed in {elapsed:.2f}s.")
        logger.info(f"Found: {found_users}")
        logger.info(f"Not found: {not_found_users}")
        logger.info(f"That's {found_users/len(users_pks)*100}%.")
        logger.info(f"Server errors: {len(server_errors)}")
        logger.info(server_errors)
