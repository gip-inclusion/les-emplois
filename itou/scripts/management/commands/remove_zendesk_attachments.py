import os

import httpx

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

    def tickets(self):
        next_page = "tickets?page=1"
        while next_page:
            data = self.get(next_page).raise_for_status().json()
            next_page = data.get("next_page")
            yield from data["tickets"]

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
    help = "Remove all attachments from closed tickets comments"

    def handle(self, **options):
        zendesk_client = ZendeskClient()

        try:
            for ticket in zendesk_client.tickets():
                if ticket["status"] != "closed":
                    continue
                for comment in zendesk_client.comments(ticket["id"]):
                    for attachment in comment["attachments"]:
                        zendesk_client.remove_attachment(ticket["id"], comment["id"], attachment["id"])
        except httpx.HTTPError as e:
            print(e.response.json()["message"])
