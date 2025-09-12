import enum
import logging
from itertools import batched

import httpx
from django.conf import settings


logger = logging.getLogger(__name__)


# https://app.brevo.com/contact/list-listing
class BrevoListID(enum.IntEnum):
    LES_EMPLOIS = 31
    CANDIDATS = 82
    CANDIDATS_AUTONOMES_BLOQUES = 83
    CANDIDATS_AUTONOMES_AVEC_DIAGNOSTIC = 116


class BrevoClient:
    IMPORT_BATCH_SIZE = 1000

    def __init__(self):
        self.client = httpx.Client(
            headers={
                "accept": "application/json",
                "api-key": settings.BREVO_API_KEY,
                "Content-Type": "application/json",
            },
            base_url=settings.BREVO_API_URL,
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
                response.text,
            )

    def import_users(self, users, list_id, serializer):
        for batch in batched(users, self.IMPORT_BATCH_SIZE):
            if batch:
                self._import_contacts(batch, list_id, serializer)

    def delete_contact(self, email):
        # Brevo rejects HTTP DELETE calls for addresses ending by
        # "_old" (status_code 400), these address are made when Support Team disable a user in admin
        # ".old", ".back", ".tar", ".zip" (status_code 403), told as fitering by CloudFlare
        # We do not want to call Brevo in that case
        if not email or email.endswith(("_old", ".old", ".back", ".tar", ".zip")):
            return
        try:
            response = self.client.delete(
                f"/contacts/{email}?identifierType=email_id",
            )
            if response.status_code == 404:
                return
            response.raise_for_status()
        except httpx.RequestError as e:
            logger.error("Brevo API: Request failed: %s", str(e))
            raise
        except httpx.HTTPStatusError as e:
            logger.error("Brevo API: Response with status_code=%s", e.response.status_code)
            raise
