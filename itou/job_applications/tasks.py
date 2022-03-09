from time import sleep

from django.conf import settings
from django.utils import timezone
from huey.contrib.djhuey import db_task

from itou.utils.apis.pole_emploi import (
    POLE_EMPLOI_PASS_APPROVED,
    PoleEmploiIndividu,
    PoleEmploiMiseAJourPassIAEException,
    mise_a_jour_pass_iae,
)


def notify_pole_emploi_pass(job_application, job_seeker, mode=POLE_EMPLOI_PASS_APPROVED):
    """
    The entire logic for notifying Pole Emploi when a job_application is accepted:
        - first, we authenticate to pole-emploi.io with the proper credentials, scopes, environment and
        dry-run/wet run settings
        - then, we search for the job_seeker on their backend. They reply with an encrypted NIR.
        - finally, we use the encrypted NIR to notify them that a job application was accepted or refused.
        We provide what we have about this job application.

    This is VERY error prone and can break in a lot of places. PE’s servers can be down, we may not find
    the job_seeker, the update may fail for various reasons. The rate limiting is low, hence…
    those terrible `sleep` for lack of a better idea for now.

    In order to ensure the rest of the application process will behave properly no matter what happens here:
     - there is a lot of broad exception catching
     - we keep logs of the successful/failed attempts
     - when anything break, we quit early
    """
    # We do not send approvals that start in the future to PE, because the information system in front
    # can’t handle them. I’ll keep my opinion about this for talks that involve an unreasonnable amount of beer.
    # Another mechanism will be in charge of sending them on their start date
    if job_application.approval.start_at > timezone.now().date():
        return False
    from itou.job_applications.models import JobApplicationPoleEmploiNotificationLog

    individual = PoleEmploiIndividu.from_job_seeker(job_seeker)
    if individual is None or not individual.is_valid():
        # We may not have a valid user (missing NIR, for instance),
        # in which case we can bypass this process entirely
        return False
    log = JobApplicationPoleEmploiNotificationLog(
        job_application=job_application, status=JobApplicationPoleEmploiNotificationLog.STATUS_OK
    )
    # Step 1: we get the API token
    try:
        token = JobApplicationPoleEmploiNotificationLog.get_token()
        sleep(1)
    except Exception as e:
        log.status = JobApplicationPoleEmploiNotificationLog.STATUS_FAIL_AUTHENTICATION
        log.details = str(e)
        log.save()
        return False
    # Step 2 : we fetch the encrypted NIR
    try:
        encrypted_nir = JobApplicationPoleEmploiNotificationLog.get_encrypted_nir_from_individual(individual, token)
        # 3 requests/second max. I had timeout issues so 1 second takes some margins
        sleep(1)
    except PoleEmploiMiseAJourPassIAEException as e:
        log = JobApplicationPoleEmploiNotificationLog(
            job_application=job_application,
            status=JobApplicationPoleEmploiNotificationLog.STATUS_FAIL_SEARCH_INDIVIDUAL,
            details=f"http_code={e.http_code} response_code={e.response_code} token={token} mode={settings.API_ESD_MISE_A_JOUR_PASS_MODE}",  # noqa
        )
        log.save()
        return False

    # despite some earlier checks, we keep having invalid encrypted indentifier errors
    if not encrypted_nir:
        log = JobApplicationPoleEmploiNotificationLog(
            job_application=job_application,
            status=JobApplicationPoleEmploiNotificationLog.STATUS_FAIL_SEARCH_INDIVIDUAL,
            details="empty encrypted nir",
        )
        log.save()
        return False
    # Step 3: we finally notify Pole Emploi that something happened for this user
    try:
        mise_a_jour_pass_iae(job_application, mode, encrypted_nir, token)
        sleep(1)
    except PoleEmploiMiseAJourPassIAEException as e:
        log.status = JobApplicationPoleEmploiNotificationLog.STATUS_FAIL_NOTIFY_POLE_EMPLOI
        # We log the encrypted nir in case its not empty but
        # it leads to an E_ERR_EX042_PROBLEME_DECHIFFREMEMENT anyway
        # This error should be fixed earlier but for some unknown reason yet, it keeps happening
        log.details = f"http_code={e.http_code} response_code={e.response_code} token={token} mode={settings.API_ESD_MISE_A_JOUR_PASS_MODE} encrypted_nir={encrypted_nir}"  # noqa
        log.save()
        return False
    log.details += f" token={token} mode={settings.API_ESD_MISE_A_JOUR_PASS_MODE}"
    log.save()
    return True


@db_task()
def huey_notify_pole_employ(job_application, mode: str):
    return notify_pole_emploi_pass(job_application, job_application.job_seeker, mode)
