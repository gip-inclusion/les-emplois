import urllib

from dateutil.relativedelta import relativedelta
from django.utils import timezone
from freezegun import freeze_time

from itou.utils.apis.github import GithubApiClient


@freeze_time("2024-12-03")
def test_request(github_respx_mock):
    start = timezone.now() - relativedelta(days=1)

    response = GithubApiClient()._request(endpoint="les-emplois/issues", start=start)
    assert urllib.parse.quote(start.isoformat()) in str(response.url)
    assert "closed" in str(response.url)
    assert "bug" in str(response.url)


@freeze_time("2024-12-03")
def test_total_pr_bugs(github_respx_mock):
    assert len(github_respx_mock._return_value.json()) == 4

    start = timezone.now() - relativedelta(days=1)
    data = GithubApiClient().get_metrics(start=start)
    assert "total_pr_bugs" in data.keys()
    assert data["total_pr_bugs"] == 2
