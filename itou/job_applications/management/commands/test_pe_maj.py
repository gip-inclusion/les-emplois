from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand

from itou.job_applications.models import JobApplicationPoleEmploiNotificationLog
from itou.utils.apis.pole_emploi import PoleEmploiIndividu


class Command(BaseCommand):
    """
    Performs a sample HTTP request to pole emploi

    When ready:
        django-admin fetch_pole_emploi --verbosity=2
    """

    help = "simplify testing the API calls"

    API_DATE_FORMAT = "%Y-%m-%d"

    # def generate_sample_api_params(self, encrypted_identifier):
    #     approval_start_at = date(2021, 11, 1)
    #     approval_end_at = date(2022, 7, 1)
    #     approved_pass = "A"
    #     approval_number = "999992139048"
    #     siae_siret = "42373532300044"
    #     prescriber_siret = "36252187900034"
    #
    #     return {
    #         "idNational": encrypted_identifier,
    #         "statutReponsePassIAE": approved_pass,
    #         "typeSIAE": PoleEmploiMiseAJourPass.kind(Siae.KIND_EI),
    #         "dateDebutPassIAE": approval_start_at.strftime(self.API_DATE_FORMAT),
    #         "dateFinPassIAE": approval_end_at.strftime(self.API_DATE_FORMAT),
    #         "numPassIAE": approval_number,
    #         "numSIRETsiae": siae_siret,
    #         "numSIRETprescripteur": prescriber_siret,
    #         "origineCandidature": PoleEmploiMiseAJourPass.sender_kind(JobApplication.SENDER_KIND_JOB_SEEKER),
    #     }

    def dump_settings(self):
        print(f"API_ESD_AUTH_BASE_URL: {settings.API_ESD_AUTH_BASE_URL}")
        print(f"API_ESD_BASE_URL:      {settings.API_ESD_BASE_URL}")
        print(f"API_ESD_KEY:           {settings.API_ESD_KEY}")
        print(f"API_ESD_SECRET:        {settings.API_ESD_SECRET}")
        print(f"API_ESD_MISE_A_JOUR_PASS_MODE:        {settings.API_ESD_MISE_A_JOUR_PASS_MODE}")

    def send_pass_update(self):
        self.dump_settings()
        # token = JobApplicationPoleEmploiNotificationLog.get_token()
        # print(token)
        individual = PoleEmploiIndividu("GREGOIRE", "DELMAS", date(1979, 6, 3), "179062452001390")
        encrypted_nir = JobApplicationPoleEmploiNotificationLog.get_encrypted_nir_from_individual(individual, "test")
        print(encrypted_nir)

    def handle(self, dry_run=False, **options):
        self.send_pass_update()
