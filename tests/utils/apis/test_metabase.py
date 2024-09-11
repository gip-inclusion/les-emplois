import pytest

from itou.utils.apis.metabase import Client


@pytest.fixture(name="client")
def client_fixture(settings):
    settings.METABASE_API_KEY = "metabase-api-key"
    return Client("http://metabase")


@pytest.fixture(name="data_results")
def data_results_fixture():
    return {
        "rows": [
            ["Value 1", 1, 1.0],
            ["Value 2", 2, 2.0],
        ],
        "cols": [
            {"id": 1, "name": "Col 1"},
            {"id": 2, "name": "Col 2"},
            {"id": 3, "name": "Col 3"},
        ],
    }


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


def test_normalize_field_to_field_name():
    columns_metadata = [
        {"id": 42, "name": "foo"},
    ]
    assert Client._normalize_field_to_field_name("foo", columns_metadata) == "foo"
    assert Client._normalize_field_to_field_name("bar", columns_metadata) == "bar"
    assert Client._normalize_field_to_field_name("42", columns_metadata) == "foo"
    assert Client._normalize_field_to_field_name(42, columns_metadata) == "foo"
    with pytest.raises(RuntimeError, match="field_id=21 was not found in columns metadata"):
        assert Client._normalize_field_to_field_name(21, columns_metadata) is None
    with pytest.raises(RuntimeError, match="field_id=21 was not found in columns metadata"):
        assert Client._normalize_field_to_field_name("21", columns_metadata) is None


def test_transform_metabase_results_shortcut():
    # No rows
    assert Client.transform_metabase_results({"rows": None}) == []
    # Single value
    assert Client.transform_metabase_results({"rows": [["Value 1"]]}, single_value=True) == "Value 1"
    # Single value, single group by
    results = {
        "rows": [
            ["Value 1", 1],
            ["Value 2", 2],
        ],
    }
    assert Client.transform_metabase_results(results, single_value=True, group_by=[None]) == {
        "Value 1": 1,
        "Value 2": 2,
    }


def test_transform_metabase_results(data_results):
    assert Client.transform_metabase_results(data_results) == [
        {"Col 1": "Value 1", "Col 2": 1, "Col 3": 1.0},
        {"Col 1": "Value 2", "Col 2": 2, "Col 3": 2.0},
    ]
    assert Client.transform_metabase_results(data_results, group_by=[1]) == {
        "Value 1": {"Col 1": "Value 1", "Col 2": 1, "Col 3": 1.0},
        "Value 2": {"Col 1": "Value 2", "Col 2": 2, "Col 3": 2.0},
    }
    assert Client.transform_metabase_results(data_results, group_by=[1, "Col 2"]) == {
        ("Value 1", 1): {"Col 1": "Value 1", "Col 2": 1, "Col 3": 1.0},
        ("Value 2", 2): {"Col 1": "Value 2", "Col 2": 2, "Col 3": 2.0},
    }
    assert Client.transform_metabase_results(data_results, group_by=[1, 2], single_value=True) == {
        ("Value 1", 1): 1.0,
        ("Value 2", 2): 2.0,
    }


@pytest.mark.respx(base_url="http://metabase/api")
def test_fetch_card_results_without_filters_nor_group_by(respx_mock, client, data_results):
    respx_mock.post("/card/42/query").respond(202, json={"data": data_results})
    assert client.fetch_card_results(42) == [
        {"Col 1": "Value 1", "Col 2": 1, "Col 3": 1.0},
        {"Col 1": "Value 2", "Col 2": 2, "Col 3": 2.0},
    ]
    assert client.fetch_card_results(42, single_value=True) == "Value 1"


@pytest.mark.respx(base_url="http://metabase/api")
def test_fetch_card_results_with_filters(snapshot, respx_mock, client, data_results):
    card_api_route = respx_mock.get("/card/42")
    dataset_api_route = respx_mock.post("/dataset").respond(202, json={"data": data_results})

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
    dataset_api_route = respx_mock.post("/dataset").respond(202, json={"data": data_results})

    # Without pre-existing breakout
    card_api_route.respond(200, json={"dataset_query": {"query": {"foo": "bar"}}})
    client.fetch_card_results(42, group_by=[1])  # We need a field referenced in data_results
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
    client.fetch_card_results(42, group_by=[2])  # We need a field referenced in data_results
    assert dataset_api_route.calls.last.request.content == snapshot(name="with pre-existing")
