import pytest
from django.test import TestCase

from itou.asp.constants import ASP_COMMUNES_AS_COUNTRIES
from itou.asp.models import Commune
from itou.asp.utils import guess_birth_place_from_nir


# NIRs in those tests have been generated with
# https://cle-nir.inclusion.gouv.fr/


@pytest.mark.parametrize(
    "nir,expected_city,expected_country",
    [
        ("199018619400167", "POITIERS", "FRANCE"),
        ("   1 99 01 86 194 001 67   ", "POITIERS", "FRANCE"),
        ("399018619400164", "POITIERS", "FRANCE"),  # NIA 3xxxx: ok
        ("499018619400114", "POITIERS", "FRANCE"),  # NIA 4xxxx: ok
        ("799018619400158", None, None),  # NIA 7xxxx: ko
        ("899018619400108", None, None),  # NIA 4xxxx: ko
        ("199019911100172", None, "BULGARIE"),
        ("199018699900170", None, "FRANCE"),  # city code 86999 does not exist
        ("199019999900110", None, None),  # country code 999 does not exist
        ("", None, None),
        ("11111", None, None),
    ],
)
def test_guess_birth_place_from_nir(nir, expected_city, expected_country):
    city, country = guess_birth_place_from_nir(nir)
    if expected_city is None:
        assert city is None
    else:
        assert city.name == expected_city
    if expected_country is None:
        assert country is None
    else:
        assert country.name == expected_country


@pytest.mark.slow  # loading fixtures takes ~30 seconds
class TestAspCommunesAsCountries(TestCase):
    fixtures = ["itou/asp/fixtures/asp_INSEE_communes.json"]

    def test_consistency(self):
        from_communes = set(Commune.objects.values_list("name", flat=True))
        from_constant = set(ASP_COMMUNES_AS_COUNTRIES)
        diff = from_constant - from_communes
        # The following diff is inevitable: these "countries" do not
        # have a corresponding commune. Hopefully, nobody was born
        # there.
        assert diff == {
            "ARCHIPEL DES CROZET",
            "ARCHIPEL DES KERGUELEN",
            "ILE DE CLIPPERTON",
            "ILE-DES-PINS (L')",
            "ILES EPARSES DE L'OCEAN INDIEN",
            "ILES SAINT-PAUL ET NOUVELLE-AMSTERDAM",
            "LA TERRE-ADELIE",
        }
