from itou.utils.constants import IMMERSION_FACILE_SITE_URL
from itou.utils.immersion_facile import immersion_search_url
from tests.users.factories import JobSeekerWithAddressFactory


def test_immersion_search_url():
    user = JobSeekerWithAddressFactory(for_snapshot=True)
    expected_url = (
        f"{IMMERSION_FACILE_SITE_URL}/recherche?"
        f"mtm_campaign=les-emplois-recherche-immersion"
        f"&mtm_kwd=les-emplois-recherche-immersion"
        f"&distanceKm=20"
        f"&latitude=0.0&longitude=0.0"
        f"&sortedBy=distance"
        f"&place=Sauvigny-les-Bois%2C%20Bourgogne-Franche-Comt%C3%A9%2C%20France"
    )
    assert immersion_search_url(user) == expected_url

    user = JobSeekerWithAddressFactory(without_geoloc=True)
    expected_url = (
        f"{IMMERSION_FACILE_SITE_URL}/recherche?"
        f"mtm_campaign=les-emplois-recherche-immersion"
        f"&mtm_kwd=les-emplois-recherche-immersion"
    )
    assert immersion_search_url(user) == expected_url
