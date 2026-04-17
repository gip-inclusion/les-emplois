import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import resolve, reverse

from tests.companies.factories import CompanyMembershipFactory


def test_http_methods_options(client):
    url = reverse("autocomplete:cities")
    view_func = resolve(url).func
    # Check that this a http_methods decorated view
    assert "GET" in view_func._db_readonly

    response = client.options(url)
    assert response.status_code == 200
    assert response.headers["Allow"] == "GET, HEAD, OPTIONS"

    assert client.post(url).status_code == 405


@pytest.mark.django_db(transaction=True)
def test_readonly_view_db_readonly(client):
    # This is a simple readonly_view decorated view
    url = reverse("autocomplete:cities")
    view_func = resolve(url).func
    # Check that this a http_methods decorated view
    assert "GET" in view_func._db_readonly

    with CaptureQueriesContext(connection) as context:
        response = client.get(url, {"term": "e"})
        assert response.status_code == 200
        # Single SQL query and it is not a BEGIN/COMMIT
        assert len(context.captured_queries) == 1
        assert context.captured_queries[0]["sql"].startswith("SELECT ")

    # Check require_http_methods behavior
    assert "PUT" not in view_func._db_readonly
    assert "PUT" not in view_func._db_write
    assert client.put(url).status_code == 405


@pytest.mark.django_db(transaction=True)
def test_readonly_view_atomic_db_write(client):
    # This is a simple readonly_view decorated view
    url = reverse("companies_views:job_description_list")
    view_func = resolve(url).func
    # Check that this a http_methods decorated view
    assert "POST" in view_func._db_write

    user = CompanyMembershipFactory().user
    # Our test view also requires a login
    client.force_login(user)

    with CaptureQueriesContext(connection) as context:
        response = client.post(
            url,
            {
                "job_description_id": 42,
                "action": "delete",
            },
        )
        assert response.status_code == 302
        # A bunch of SQL queries with a BEGIN somewhere and a COMMIT at the end
        assert context.captured_queries
        assert any(query["sql"] == "BEGIN" for query in context.captured_queries)
        assert context.captured_queries[-1]["sql"] == "COMMIT"

    # Check require_http_methods behavior
    assert "PUT" not in view_func._db_readonly
    assert "PUT" not in view_func._db_write
    assert client.put(url).status_code == 405
