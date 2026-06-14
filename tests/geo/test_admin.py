import pytest
from django.urls import reverse

from tests.geo.factories import create_qpv
from tests.users.factories import ItouStaffFactory


@pytest.fixture
def admin_client(client, db):
    admin = ItouStaffFactory(is_staff=True, is_superuser=True)
    client.force_login(admin)
    return client


@pytest.mark.parametrize(
    "url_name,policy",
    [
        ("admin:geo_qpv_change", "strict-origin-when-cross-origin"),
        ("admin:geo_qpv_changelist", "same-origin"),
    ],
)
def test_referrer_policy_for_map_tiles(admin_client, url_name, policy):
    """The QPV change page render the GeoDjango OpenStreetMap map widget, whose tiles are loaded cross-origin.

    This specific page must override the site-wide `same-origin` policy so the browser sends a `Referer` to OSM
    (else the tiles are blocked). Other pages like the changelist have no map and must keep the strict global default,
    proving the relaxation is scoped to the GIS change form page only.

    See also: https://wiki.openstreetmap.org/wiki/Blocked_tiles#If_you_are_the_owner/a_developer_of_the_application/website
    """
    qpv = create_qpv("QP075019")
    args = [qpv.pk] if url_name == "admin:geo_qpv_change" else []
    response = admin_client.get(reverse(url_name, args=args))
    assert response.status_code == 200
    assert response.headers["Referrer-Policy"] == policy
