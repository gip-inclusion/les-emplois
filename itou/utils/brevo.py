import enum
import logging
from itertools import batched

import httpx
from django.conf import settings


logger = logging.getLogger(__name__)

BREVO_API_URL = "https://api.brevo.com/v3"


# https://app.brevo.com/contact/list-listing
class BrevoListID(enum.IntEnum):
    LES_EMPLOIS = 31
    CANDIDATS = 82
    CANDIDATS_AUTONOMES_BLOQUES = 83


class BrevoClient:
    IMPORT_BATCH_SIZE = 1000

    def __init__(self):
        self.client = httpx.Client(
            headers={
                "accept": "application/json",
                "api-key": settings.BREVO_API_KEY,
            },
        )

    def _import_contacts(self, users, list_id, serializer):
        response = self.client.post(
            f"{BREVO_API_URL}/contacts/import",
            headers={"Content-Type": "application/json"},
            json={
                "listIds": [list_id],
                "emailBlacklist": False,
                "smsBlacklist": False,
                "updateExistingContacts": False,  # Don't update because we don't want to update emailBlacklist
                "emptyContactsAttributes": False,
                "jsonBody": [serializer(user) for user in users],
            },
        )
        if response.status_code != 202:
            logger.error(
                "Brevo API: Some emails were not imported, status_code=%d, content=%s",
                response.status_code,
                response.text,
            )

    def import_users(self, users, list_id, serializer):
        for batch in batched(users, self.IMPORT_BATCH_SIZE):
            if batch:
                self._import_contacts(batch, list_id, serializer)
