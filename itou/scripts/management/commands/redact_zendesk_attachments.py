import datetime
import os
from urllib.parse import urlencode

import httpx
from django.utils import timezone

from itou.utils.command import BaseCommand


ZENDESK_LOGIN = os.getenv("ZENDESK_LOGIN")
ZENDESK_SECRET = os.getenv("ZENDESK_SECRET")


class ZendeskClient:
    def __init__(self):
        self.auth = httpx.BasicAuth(ZENDESK_LOGIN, ZENDESK_SECRET)
        self.headers = {"Content-Type": "application/json"}
        self.base_url = "https://plateforme-inclusion.zendesk.com/api/v2/"

    def full_url(self, url):
        # api next_page urls are full url but allowing only the api part make testing new endpoints easier
        if not url.startswith("https"):
            url = f"{self.base_url}{url}"
        return url

    def get(self, url):
        return httpx.get(self.full_url(url), auth=self.auth, headers=self.headers)

    def put(self, url, data=None):
        return httpx.put(self.full_url(url), auth=self.auth, headers=self.headers, data=data)

    def get_tickets_to_clean(self):
        # Get tikets solved 7 days ago and still not closed with attachments
        search_params = [
            "type:ticket",
            "status:solved",
            f"solved<{(timezone.localdate() - datetime.timedelta(days=7)).strftime('%Y-%m-%d')}",
            "has_attachment:true",
        ]
        next_page = "search?" + urlencode({"query": " ".join(search_params)})
        while next_page:
            data = self.get(next_page).raise_for_status().json()
            next_page = data.get("next_page")
            yield from data["results"]

    def comments(self, ticket_id):
        next_page = f"tickets/{ticket_id}/comments?page=1"
        while next_page:
            data = self.get(next_page).raise_for_status().json()
            next_page = data.get("next_page")
            yield from data["comments"]

    def remove_attachment(self, ticket_id, comment_id, attachment_id):
        return self.put(
            f"{self.base_url}tickets/{ticket_id}/comments/{comment_id}/attachments/{attachment_id}/redact"
        ).raise_for_status()


class Command(BaseCommand):
    help = "Remove all attachments from solved tickets after a week"

    def handle(self, **options):
        zendesk_client = ZendeskClient()

        try:
            for ticket in zendesk_client.get_tickets_to_clean():
                ticket_id = ticket["id"]
                for comment in zendesk_client.comments(ticket_id):
                    for attachment in comment["attachments"]:
                        if attachment["file_name"] != "redacted.txt":
                            self.logger.info(
                                "Redacted attachement on ticket_id=%d comment_id=%d attachement_id=%d",
                                ticket_id,
                                comment["id"],
                                attachment["id"],
                            )
                            zendesk_client.remove_attachment(ticket_id, comment["id"], attachment["id"])

        except httpx.HTTPError as e:
            print(e.response.json()["message"])
