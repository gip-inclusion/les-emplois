import pytest

from itou.utils.apis.metabase import Client


@pytest.fixture(name="client")
def client_fixture(settings):
    settings.METABASE_API_KEY = "metabase-api-key"
    return Client("http://metabase")


@pytest.fixture(name="data_results")
def data_results_fixture():
    return [
        {"Col 1": "Value 1", "Col 2": 1, "Col 3": 1.0},
        {"Col 1": "Value 2", "Col 2": 2, "Col 3": 2.0},
    ]


@pytest.fixture(name="card_results")
def card_results_fixture():
    return {
        "dataset_query": {
            "query": {
                "filter": [],
                "breakout": [],
            }
        }
    }


@pytest.mark.parametrize("url", ["http://metabase", "http://metabase/"])
def test_client_init(faker, settings, url):
    settings.METABASE_API_KEY = faker.word()

    client = Client(url)
    assert client._client.base_url == "http://metabase/api/"
    assert client._client.headers["X-API-KEY"] == settings.METABASE_API_KEY
    assert client._client.timeout.as_dict() == {
        "connect": 5,
        "read": 60,
        "write": 5,
        "pool": 5,
    }


@pytest.mark.respx(base_url="http://metabase/api")
def test_fetch_card_results_without_filters_nor_group_by(respx_mock, client, data_results):
    respx_mock.post("/card/42/query/json").respond(202, json=data_results)
    assert client.fetch_card_results(42) == data_results


@pytest.mark.respx(base_url="http://metabase/api")
def test_fetch_card_results_with_filters(snapshot, respx_mock, client, data_results):
    card_api_route = respx_mock.get("/card/42")
    dataset_api_route = respx_mock.post("/dataset/json").respond(202, json=data_results)

    # Without pre-existing filters
    card_api_route.respond(200, json={"dataset_query": {"query": {"foo": "bar"}}})
    client.fetch_card_results(42, filters={21: ["baz"]})
    assert dataset_api_route.calls.last.request.content == snapshot(name="without pre-existing")

    # With pre-existing filters
    card_api_route.respond(
        200,
        json={
            "dataset_query": {
                "query": {
                    "filter": ["and", ["=", Client._build_metabase_field(100), "filter value 1", "filter value 2"]],
                }
            }
        },
    )
    client.fetch_card_results(42, filters={21: ["baz"]})
    assert dataset_api_route.calls.last.request.content == snapshot(name="with pre-existing")


@pytest.mark.respx(base_url="http://metabase/api")
def test_fetch_card_results_with_group_by(snapshot, respx_mock, client, data_results):
    card_api_route = respx_mock.get("/card/42")
    dataset_api_route = respx_mock.post("/dataset/json").respond(202, json=data_results)

    # Without pre-existing breakout
    card_api_route.respond(200, json={"dataset_query": {"query": {"foo": "bar"}}})
    client.fetch_card_results(42, group_by=[1])
    assert dataset_api_route.calls.last.request.content == snapshot(name="without pre-existing")

    # With pre-existing breakout
    card_api_route.respond(
        200,
        json={
            "dataset_query": {
                "query": {
                    "breakout": [client._build_metabase_field(100)],
                }
            }
        },
    )
    client.fetch_card_results(42, group_by=[2])
    assert dataset_api_route.calls.last.request.content == snapshot(name="with pre-existing")
