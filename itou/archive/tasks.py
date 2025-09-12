import logging

from huey.contrib.djhuey import on_commit_task

from itou.utils.brevo import BrevoClient


logger = logging.getLogger(__name__)


@on_commit_task(retries=90, retry_delay=24 * 60 * 60, context=True)  # Retry once a day during 90 days.
def async_delete_contact(email, *, task=None):
    with BrevoClient() as brevo_client:
        if task.retries % 100 == 0:
            logger.warning("Attempting to delete email %s, remaining %d retries", email, task.retries)
        brevo_client.delete_contact(email)
