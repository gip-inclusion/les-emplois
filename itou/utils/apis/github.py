import datetime
import logging

import httpx
import tenacity
from django.conf import settings


logger = logging.getLogger(__name__)


class GithubApiClient:
    MAX_RESULTS_PER_PAGE = 100

    def __init__(self):
        self.client = httpx.Client(
            base_url=f"{settings.API_GITHUB_BASE_URL}/repos/gip-inclusion/",
            # Authentication is not required as our repo is public.
            headers={
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    @tenacity.retry(wait=tenacity.wait_fixed(2), stop=tenacity.stop_after_attempt(8))
    def _request(self, endpoint, start):
        params = {
            "labels": ["bug"],
            "state": "closed",
            "pulls": True,
            "per_page": self.MAX_RESULTS_PER_PAGE,
            "since": start.isoformat(),  # The GH API does not allow an end date.
        }

        return self.client.get(endpoint, params=params).raise_for_status()

    @staticmethod
    def filter_by_merged_at(data, date):
        filtered_data = []
        for datum in data:
            if not datum["pull_request"].get("merged_at"):
                continue

            if datetime.datetime.fromisoformat(datum["pull_request"]["merged_at"]).date() == date:
                filtered_data.append(datum)

        return filtered_data

    def get_metrics(self, start):
        response = self._request(endpoint="les-emplois/issues", start=start)
        if len(response.json()) == self.MAX_RESULTS_PER_PAGE:
            logger.error(f"Pagination required: {len(response.json())} results returned.")

        # Filter results based on `date` because the API does not allow to pass an end date.
        today_data = self.filter_by_merged_at(data=response.json(), date=start.date())
        return {"total_pr_bugs": len(today_data)}
