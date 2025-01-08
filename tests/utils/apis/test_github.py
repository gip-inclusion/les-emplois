import urllib

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
