import pytest

from itou.metabase.tables.siaes import TABLE
from tests.cities.factories import create_city_vannes
from tests.companies.factories import SiaeFactory


@pytest.mark.django_db
def test_address_fields():
    vannes = create_city_vannes()
    parent = SiaeFactory(source="ASP", post_code=vannes.post_codes[0])
    antenna = SiaeFactory(source="USER_CREATED", convention=parent.convention)
    assert TABLE.get(column_name="adresse_ligne_1", input=antenna) == parent.address_line_1
    assert TABLE.get(column_name="adresse_ligne_2", input=antenna) == parent.address_line_2
    assert TABLE.get(column_name="code_postal", input=antenna) == parent.post_code
    assert TABLE.get(column_name="code_commune", input=antenna) != parent.post_code
    assert TABLE.get(column_name="code_commune", input=antenna) == vannes.code_insee
    assert TABLE.get(column_name="ville", input=antenna) == parent.city
    assert TABLE.get(column_name="département", input=antenna) == parent.department
