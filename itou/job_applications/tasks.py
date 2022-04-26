import logging
from time import sleep

from django.utils import timezone
from huey.contrib.djhuey import db_task

from itou.utils.apis.pole_emploi import PoleEmploiIndividu, PoleEmploiMiseAJourPassIAEException, mise_a_jour_pass_iae


# 3 requests/second max. There were timeout issues so 1 second takes some margins
SLEEP_DELAY = 1.0

logger = logging.getLogger(__name__)


def notify_pole_emploi_pass(job_application, job_seeker):
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
        logger.info("! job_application starts after today, skipping.")
        return False
    from itou.job_applications.models import JobApplicationPoleEmploiNotificationLog

    individual = PoleEmploiIndividu.from_job_seeker(job_seeker)
    if individual is None or not individual.is_valid():
        # We may not have a valid user (missing NIR, for instance),
        # in which case we can bypass this process entirely
        logger.info("! job_application had an invalid user, skipping.")
        return False
    log = JobApplicationPoleEmploiNotificationLog(
        job_application=job_application, status=JobApplicationPoleEmploiNotificationLog.STATUS_OK
    )
    # Step 1: we get the API token
    try:
        token = JobApplicationPoleEmploiNotificationLog.get_token()
        sleep(SLEEP_DELAY)
    except Exception as e:
        logger.error("! fetching token raised exception=%s", e)
        log.status = JobApplicationPoleEmploiNotificationLog.STATUS_FAIL_AUTHENTICATION
        log.details = str(e)
        log.save()
        return False

    # Step 2 : we fetch the encrypted NIR
    try:
        encrypted_nir = JobApplicationPoleEmploiNotificationLog.get_encrypted_nir_from_individual(individual, token)
        logger.info("> got encrypted_nir=%s", encrypted_nir)
        sleep(SLEEP_DELAY)
    except PoleEmploiMiseAJourPassIAEException as e:
        logger.error("! fetching encrypted NIR raised http_code=%s message=%s", e.http_code, e.response_code)
        log = JobApplicationPoleEmploiNotificationLog(
            job_application=job_application,
            status=JobApplicationPoleEmploiNotificationLog.STATUS_FAIL_SEARCH_INDIVIDUAL,
            details=f"http_code={e.http_code} response_code={e.response_code} token={token}",  # noqa
        )
        log.save()
        return False

    # Step 3: we finally notify Pole Emploi that something happened for this user
    try:
        mise_a_jour_pass_iae(job_application, encrypted_nir, token)
        logger.info("> pass nir=%s updated successfully", job_application.job_seeker.nir)
        sleep(SLEEP_DELAY)
    except PoleEmploiMiseAJourPassIAEException as e:
        logger.error("! updating pass iae raised http_code=%s message=%s", e.http_code, e.response_code)
        log.status = JobApplicationPoleEmploiNotificationLog.STATUS_FAIL_NOTIFY_POLE_EMPLOI
        # We log the encrypted nir in case its not empty but
        # it leads to an E_ERR_EX042_PROBLEME_DECHIFFREMEMENT anyway
        # This error should be fixed earlier but for some unknown reason yet, it keeps happening
        log.details = f"http_code={e.http_code} response_code={e.response_code} token={token} encrypted_nir={encrypted_nir}"  # noqa
        log.save()
        return False
    log.details += f" token={token}"
    log.save()
    return True


@db_task()
def huey_notify_pole_employ(job_application):
    return notify_pole_emploi_pass(job_application, job_application.job_seeker)
