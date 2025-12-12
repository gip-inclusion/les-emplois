import json
import pathlib

import pytest
from django.urls import reverse_lazy


class TestMonRecapApi:
    ENDPOINT_URL = reverse_lazy("v1:mon-recap-submit")
    PAYLOAD = json.loads(pathlib.Path("tests/api/mon_recap_api/tally.json").read_text())

    @pytest.fixture(autouse=True)
    def setup_method(self, settings):
        settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] |= {"mon-recap-submit": "10/minute"}

    @pytest.mark.parametrize(
        "method_name,expected",
        [
            ("get", 405),
            ("post", 201),
            ("put", 405),
            ("patch", 405),
            ("delete", 405),
            ("head", 405),
            ("options", 200),
        ],
    )
    def test_http_method(self, api_client, method_name, expected):
        http_method = getattr(api_client, method_name)
        response = http_method(self.ENDPOINT_URL, self.PAYLOAD, format="json")
        assert response.status_code == expected
