import datetime
import json
import os
import urllib

from django.conf import settings

from itou.utils.apis.github import GithubApiClient


def test_request(github_respx_mock):
    start, _ = github_respx_mock
    response = GithubApiClient()._request(endpoint="les-emplois/issues", start=start)
    assert urllib.parse.quote(start.isoformat()) in str(response.url)
    assert "closed" in str(response.url)
    assert "bug" in str(response.url)


def test_total_pr_bugs(github_respx_mock):
    start, mock = github_respx_mock
    assert len(mock._return_value.json()) == 4

    data = GithubApiClient().get_metrics(start=start)
    assert "total_pr_bugs" in data.keys()
    assert data["total_pr_bugs"] == 2


def test_pagination_required(respx_mock, mocker, caplog):
    with open(os.path.join(settings.ROOT_DIR, "tests", "data", "github.json")) as file:
        resp_json = json.load(file)

    mocker.patch.object(GithubApiClient, "MAX_RESULTS_PER_PAGE", len(resp_json))

    start = datetime.datetime(2024, 12, 2, tzinfo=datetime.UTC)
    params = {
        "labels": ["bug"],
        "state": "closed",
        "pulls": True,
        "per_page": GithubApiClient.MAX_RESULTS_PER_PAGE,
        "since": start.isoformat(),
    }
    headers = {
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    url = f"{settings.API_GITHUB_BASE_URL}/repos/gip-inclusion/les-emplois/issues"
    respx_mock.route(headers=headers, method="GET", params=params, url=url).respond(json=resp_json)

    GithubApiClient().get_metrics(start=start)
    assert "Pagination required: 4 results returned." in caplog.messages
