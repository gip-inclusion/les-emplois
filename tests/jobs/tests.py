from itou.jobs.models import Appellation, Rome
from tests.jobs.factories import create_test_romes_and_appellations


def test_create_test_romes_and_appellations():
    create_test_romes_and_appellations(["M1805", "N1101"], appellations_per_rome=2)
    assert Rome.objects.count() == 2
    assert Appellation.objects.count() == 4
    assert Appellation.objects.filter(rome_id="M1805").count() == 2
    assert Appellation.objects.filter(rome_id="N1101").count() == 2


def test_appellation_autocomplete():
    create_test_romes_and_appellations(["N1101", "N4105"])

    [appellation] = Appellation.objects.autocomplete("conducteur lait")
    assert appellation.code == "12859"
    assert appellation.name == "Conducteur collecteur / Conductrice collectrice de lait"

    [appellation] = Appellation.objects.autocomplete("chariot armee")
    assert appellation.code == "12918"
    assert appellation.name == "Conducteur / Conductrice de chariot élévateur de l'armée"

    # with rome_code
    appellation = Appellation.objects.autocomplete("conducteur", limit=1, rome_code="N1101")[0]
    assert appellation.code == "12918"
    assert appellation.name == "Conducteur / Conductrice de chariot élévateur de l'armée"

    appellation = Appellation.objects.autocomplete("conducteur", limit=1, rome_code="N4105")[0]
    assert appellation.code == "12859"
    assert appellation.name == "Conducteur collecteur / Conductrice collectrice de lait"
