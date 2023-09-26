from datetime import datetime, timezone

import pytest
from django.test import override_settings
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertQuerySetEqual

from itou.analytics.models import StatsDashboardVisit
from itou.common_apps.address.departments import DEPARTMENT_TO_REGION
from itou.institutions.enums import InstitutionKind
from itou.utils.apis.metabase import METABASE_DASHBOARDS
from tests.institutions.factories import InstitutionWithMembershipFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.siaes.factories import SiaeFactory
from tests.users.factories import PrescriberFactory
from tests.utils.test import TestCase


class StatsViewTest(TestCase):
    @override_settings(METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar")
    def test_stats_public(self):
        url = reverse("stats:stats_public")
        response = self.client.get(url)
        assert response.status_code == 200

    def test_stats_pilotage_unauthorized_dashboard_id(self):
        url = reverse("stats:stats_pilotage", kwargs={"dashboard_id": 123})
        response = self.client.get(url)
        assert response.status_code == 403

    @override_settings(
        PILOTAGE_DASHBOARDS_WHITELIST=[123], METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar"
    )
    def test_stats_pilotage_authorized_dashboard_id(self):
        url = reverse("stats:stats_pilotage", kwargs={"dashboard_id": 123})
        response = self.client.get(url)
        assert response.status_code == 200

    @override_settings(
        PILOTAGE_DASHBOARDS_WHITELIST=[123], METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar"
    )
    def test_stats_pilotage_authorized_dashboard_id_while_authenticated(self):
        user = PrescriberFactory()
        self.client.force_login(user)
        url = reverse("stats:stats_pilotage", kwargs={"dashboard_id": 123})
        response = self.client.get(url)
        assert response.status_code == 200


def assert_stats_dashboard_equal(values):
    assertQuerySetEqual(
        StatsDashboardVisit.objects.all(),
        [
            values,
        ],
        transform=lambda visit: (
            visit.dashboard_id,
            visit.dashboard_name,
            visit.department,
            visit.region,
            visit.current_siae_id,
            visit.current_prescriber_organization_id,
            visit.current_institution_id,
            visit.user_kind,
            visit.user_id,
            visit.measured_at,
        ),
    )


@freeze_time("2023-03-10")
@override_settings(METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar")
@pytest.mark.parametrize(
    "view_name",
    [
        "stats_pe_delay_main",
        "stats_pe_delay_raw",
        "stats_pe_conversion_main",
        "stats_pe_conversion_raw",
        "stats_pe_state_main",
        "stats_pe_state_raw",
        "stats_pe_tension",
    ],
)
def test_stats_prescriber_log_visit(client, view_name):
    prescriber_org = PrescriberOrganizationWithMembershipFactory(authorized=True)
    user = prescriber_org.members.get()
    client.force_login(user)

    assertQuerySetEqual(StatsDashboardVisit.objects.all(), [])

    response = client.get(reverse(f"stats:{view_name}"))
    assert response.status_code == 200

    assert_stats_dashboard_equal(
        (
            METABASE_DASHBOARDS.get(view_name)["dashboard_id"],
            view_name,
            prescriber_org.department,
            DEPARTMENT_TO_REGION[prescriber_org.department],
            None,
            prescriber_org.pk,
            None,
            user.kind,
            user.pk,
            datetime(2023, 3, 10, tzinfo=timezone.utc),
        ),
    )


@freeze_time("2023-03-10")
@pytest.mark.parametrize(
    "view_name",
    [
        "stats_siae_etp",
        "stats_siae_hiring",
    ],
)
def test_stats_siae_log_visit(client, view_name, settings):
    siae = SiaeFactory(name="El garaje de la esperanza", with_membership=True)
    user = siae.members.get()

    settings.METABASE_SITE_URL = "http://metabase.fake"
    settings.METABASE_SECRET_KEY = "foobar"
    settings.STATS_SIAE_USER_PK_WHITELIST = [user.pk]

    client.force_login(user)

    assertQuerySetEqual(StatsDashboardVisit.objects.all(), [])

    response = client.get(reverse(f"stats:{view_name}"))
    assert response.status_code == 200

    assert_stats_dashboard_equal(
        (
            METABASE_DASHBOARDS.get(view_name)["dashboard_id"],
            view_name,
            siae.department,
            DEPARTMENT_TO_REGION[siae.department],
            siae.pk,
            None,
            None,
            user.kind,
            user.pk,
            datetime(2023, 3, 10, tzinfo=timezone.utc),
        ),
    )


@freeze_time("2023-03-10")
@override_settings(METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar")
@pytest.mark.parametrize(
    "view_name",
    [
        "stats_ddets_iae_auto_prescription",
        "stats_ddets_iae_follow_siae_evaluation",
        "stats_ddets_iae_follow_prolongation",
        "stats_ddets_iae_iae",
        "stats_ddets_iae_siae_evaluation",
        "stats_ddets_iae_hiring",
    ],
)
def test_stats_ddets_iae_log_visit(client, view_name):
    institution = InstitutionWithMembershipFactory(kind=InstitutionKind.DDETS_IAE, department="22")
    user = institution.members.get()
    client.force_login(user)

    assertQuerySetEqual(StatsDashboardVisit.objects.all(), [])

    url = reverse(f"stats:{view_name}")
    response = client.get(url)
    assert response.status_code == 200
    # Check that the base slash of the URL is not included; it's added by the Javascript.
    assert response.context["matomo_custom_url"] == f"{url[1:]}/Bretagne/22---Cotes-d-Armor"

    assert_stats_dashboard_equal(
        (
            METABASE_DASHBOARDS.get(view_name)["dashboard_id"],
            view_name,
            institution.department,
            DEPARTMENT_TO_REGION[institution.department],
            None,
            None,
            institution.pk,
            user.kind,
            user.pk,
            datetime(2023, 3, 10, tzinfo=timezone.utc),
        ),
    )


@freeze_time("2023-03-10")
@override_settings(METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar")
@pytest.mark.parametrize(
    "view_name",
    [
        "stats_dreets_iae_auto_prescription",
        "stats_dreets_iae_follow_siae_evaluation",
        "stats_dreets_iae_follow_prolongation",
        "stats_dreets_iae_iae",
        "stats_dreets_iae_hiring",
    ],
)
def test_stats_dreets_iae_log_visit(client, view_name):
    institution = InstitutionWithMembershipFactory(kind="DREETS IAE")
    user = institution.members.get()
    client.force_login(user)

    assertQuerySetEqual(StatsDashboardVisit.objects.all(), [])

    response = client.get(reverse(f"stats:{view_name}"))
    assert response.status_code == 200

    assert_stats_dashboard_equal(
        (
            METABASE_DASHBOARDS.get(view_name)["dashboard_id"],
            view_name,
            None,
            DEPARTMENT_TO_REGION[institution.department],
            None,
            None,
            institution.pk,
            user.kind,
            user.pk,
            datetime(2023, 3, 10, tzinfo=timezone.utc),
        ),
    )


@freeze_time("2023-03-10")
@override_settings(METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar")
@pytest.mark.parametrize(
    "view_name",
    [
        "stats_dgefp_auto_prescription",
        "stats_dgefp_follow_siae_evaluation",
        "stats_dgefp_iae",
        "stats_dgefp_siae_evaluation",
        "stats_dgefp_af",
    ],
)
def test_stats_dgefp_log_visit(client, view_name):
    institution = InstitutionWithMembershipFactory(kind="DGEFP")
    user = institution.members.get()
    client.force_login(user)

    assertQuerySetEqual(StatsDashboardVisit.objects.all(), [])

    response = client.get(reverse(f"stats:{view_name}"))
    assert response.status_code == 200

    assert_stats_dashboard_equal(
        (
            METABASE_DASHBOARDS.get(view_name)["dashboard_id"],
            view_name,
            None,
            None,
            None,
            None,
            institution.pk,
            user.kind,
            user.pk,
            datetime(2023, 3, 10, tzinfo=timezone.utc),
        ),
    )
