import pytest

from itou.geo.utils import coords_to_geometry
from itou.metabase.tables.utils import get_code_commune, get_qpv_job_seeker_pks, get_zrr_status_for_insee_code
from tests.cities.factories import create_test_cities
from tests.geo.factories import QPVFactory, ZRRFactory
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import JobSeekerFactory


def test_get_qpv_job_seeker_pks():
    QPVFactory(code="QP093028")

    # Somewhere in QPV QP093028 (Aubervilliers)
    job_seeker_in_qpv = JobSeekerFactory(coords=coords_to_geometry("48.917735", "2.387311"), geocoding_score=0.9)

    # Somewhere not in a QPV near Aubervilliers
    job_seeker_not_in_qpv = JobSeekerFactory(coords=coords_to_geometry("48.899", "2.412"))

    assert job_seeker_in_qpv.pk in get_qpv_job_seeker_pks()
    assert job_seeker_not_in_qpv.pk not in get_qpv_job_seeker_pks()


def test_get_zrr_status_for_unknown_insee_code():
    assert get_zrr_status_for_insee_code("12345") == "Statut ZRR inconnu"


def test_get_zrr_status_for_insee_code_in_zrr():
    in_zrr = ZRRFactory(in_zrr=True)
    assert get_zrr_status_for_insee_code(in_zrr.insee_code) == "Classée en ZRR"


def test_get_zrr_status_for_insee_code_not_in_zrr():
    not_in_zrr = ZRRFactory(not_in_zrr=True)
    assert get_zrr_status_for_insee_code(not_in_zrr.insee_code) == "Non-classée en ZRR"


def test_get_zrr_status_for_insee_code_partially_in_zrr():
    partially_in_zrr = ZRRFactory(partially_in_zrr=True)
    assert get_zrr_status_for_insee_code(partially_in_zrr.insee_code) == "Partiellement classée en ZRR"


@pytest.mark.parametrize(
    "post_code,city,expected_code_insee",
    [
        # Proper case
        ("62000", "Arras", "62041"),
        ("62000", "Dainville", "62263"),
        # All uppercase
        ("73000", "CHAMBERY", "73065"),
        ("73000", "SONNAZ", "73288"),
        # Districts
        ("75001", "Paris 1er Arrondissement", "75101"),
        ("75001", "PARIS", "75056"),
    ],
)
def test_get_code_commune(post_code, city, expected_code_insee):
    create_test_cities(selected_departments=[post_code[:2]])
    organization = PrescriberOrganizationFactory.build(insee_city=None, post_code=post_code, city=city)
    assert get_code_commune(organization) == expected_code_insee
