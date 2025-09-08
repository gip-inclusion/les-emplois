import json
import pathlib

from itou.asp.models import Country


def test_france_primary_key():
    """Check the PK used by the 'jobseekerprofile_birth_country_and_place' constraint doesn't change."""

    # Check the constant used by our code
    assert Country.FRANCE_ID == 91
    # Check the loaded fixtures in tests, and production at the time of writing, are OK
    assert Country.objects.get(code=100).pk == 91
    # Check the data in the fixture file is OK
    assert {
        "model": "asp.Country",
        "pk": 91,
        "fields": {"code": 100, "name": "FRANCE", "group": 1, "department": 99},
    } in json.loads(pathlib.Path("itou/asp/fixtures/asp_INSEE_countries.json").read_text())
