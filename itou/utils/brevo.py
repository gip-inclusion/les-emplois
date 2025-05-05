import logging
from itertools import batched

import httpx
from django.conf import settings

from itou.utils.constants import BREVO_API_URL


logger = logging.getLogger(__name__)


class BrevoClient:
    IMPORT_BATCH_SIZE = 1000

    def __init__(self):
        self.client = httpx.Client(
            headers={
                "accept": "application/json",
                "api-key": settings.BREVO_API_KEY,
                "Content-Type": "application/json",
            },
            base_url=BREVO_API_URL,
            timeout=10,
        )

    # context manager
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            self.client.close()

        if exc_type:
            logger.error("An exception occurred in BrevoClient: %s", exc_val, exc_info=(exc_type, exc_val, exc_tb))

        return False

    def _import_contacts(self, users, list_id, serializer):
        try:
            response = self.client.post(
                "/contacts/import",
                json={
                    "listIds": [list_id],
                    "emailBlacklist": False,
                    "smsBlacklist": False,
                    "updateExistingContacts": False,  # Don't update because we don't want to update emailBlacklist
                    "emptyContactsAttributes": False,
                    "jsonBody": [serializer(user) for user in users],
                },
            )
        except httpx.RequestError as e:
            logger.error("Brevo API: Request failed: %s", str(e))
            raise
        if response.status_code != 202:
            logger.error(
                "Brevo API: Some emails were not imported, status_code=%d, content=%s",
                response.status_code,
                response.content.decode(),
            )

    def import_users(self, users, list_id, serializer):
        for batch in batched(users, self.IMPORT_BATCH_SIZE):
            if batch:
                self._import_contacts(batch, list_id, serializer)
