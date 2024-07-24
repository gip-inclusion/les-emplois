from datetime import UTC, datetime

import factory
import pytest
from django.test import override_settings
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertQuerySetEqual

from itou.analytics.models import StatsDashboardVisit
from itou.common_apps.address.departments import DEPARTMENT_TO_REGION
from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from itou.institutions.enums import InstitutionKind
from itou.utils.apis.metabase import METABASE_DASHBOARDS
from itou.www.stats import urls as stats_urls
from itou.www.stats.views import get_params_aci_asp_ids_for_department
from tests.companies.factories import CompanyFactory
from tests.institutions.factories import InstitutionWithMembershipFactory
from tests.prescribers.factories import \
    PrescriberOrganizationWithMembershipFactory
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
            visit.current_company_id,
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
    [p.name for p in stats_urls.urlpatterns if p.name.startswith("stats_pe_")],
)
def test_stats_pe_log_visit(client, view_name):
    prescriber_org = PrescriberOrganizationWithMembershipFactory(kind="PE", authorized=True)
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
            datetime(2023, 3, 10, tzinfo=UTC),
        ),
    )


@freeze_time("2023-03-10")
@override_settings(METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar")
@pytest.mark.parametrize(
    "view_name",
    [p.name for p in stats_urls.urlpatterns if p.name.startswith("stats_cd_")],
)
def test_stats_cd_log_visit(client, settings, view_name):
    prescriber_org = PrescriberOrganizationWithMembershipFactory(kind="DEPT", authorized=True)
    user = prescriber_org.members.get()

    settings.STATS_CD_DEPARTMENT_WHITELIST = [prescriber_org.department]
    settings.STATS_ACI_DEPARTMENT_WHITELIST = [prescriber_org.department]

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
            datetime(2023, 3, 10, tzinfo=UTC),
        ),
    )


@freeze_time("2023-03-10")
@override_settings(METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar")
@pytest.mark.parametrize(
    "view_name",
    [p.name for p in stats_urls.urlpatterns if p.name.startswith("stats_siae_")],
)
def test_stats_siae_log_visit(client, settings, view_name):
    company = CompanyFactory(name="El garaje de la esperanza", kind="ACI", with_membership=True)
    user = company.members.get()

    settings.STATS_SIAE_USER_PK_WHITELIST = [user.pk]
    settings.STATS_SIAE_PK_WHITELIST = [company.pk]
    settings.STATS_SIAE_HIRING_REPORT_REGION_WHITELIST = [company.region]
    settings.STATS_ACI_DEPARTMENT_WHITELIST = [company.department]

    client.force_login(user)

    assertQuerySetEqual(StatsDashboardVisit.objects.all(), [])

    response = client.get(reverse(f"stats:{view_name}"))
    assert response.status_code == 200

    assert_stats_dashboard_equal(
        (
            METABASE_DASHBOARDS.get(view_name)["dashboard_id"],
            view_name,
            company.department,
            DEPARTMENT_TO_REGION[company.department],
            company.pk,
            None,
            None,
            user.kind,
            user.pk,
            datetime(2023, 3, 10, tzinfo=UTC),
        ),
    )


@freeze_time("2023-03-10")
@override_settings(METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar")
@pytest.mark.parametrize(
    "view_name",
    [p.name for p in stats_urls.urlpatterns if p.name.startswith("stats_ddets_iae_")],
)
def test_stats_ddets_iae_log_visit(client, settings, view_name):
    institution = InstitutionWithMembershipFactory(kind="DDETS IAE", department="22")
    user = institution.members.get()

    settings.STATS_ACI_DEPARTMENT_WHITELIST = [institution.department]
    settings.STATS_PH_PRESCRIPTION_REGION_WHITELIST = [institution.region]

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
            datetime(2023, 3, 10, tzinfo=UTC),
        ),
    )


@freeze_time("2023-03-10")
@override_settings(METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar")
@pytest.mark.parametrize(
    "view_name",
    [p.name for p in stats_urls.urlpatterns if p.name.startswith("stats_ddets_log_")],
)
def test_stats_ddets_log_log_visit(client, settings, view_name):
    institution = InstitutionWithMembershipFactory(kind="DDETS LOG")
    user = institution.members.get()
    client.force_login(user)

    assertQuerySetEqual(StatsDashboardVisit.objects.all(), [])

    url = reverse(f"stats:{view_name}")
    response = client.get(url)
    assert response.status_code == 200

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
            datetime(2023, 3, 10, tzinfo=UTC),
        ),
    )


@freeze_time("2023-03-10")
@override_settings(METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar")
@pytest.mark.parametrize(
    "view_name",
    [p.name for p in stats_urls.urlpatterns if p.name.startswith("stats_dreets_iae_")],
)
def test_stats_dreets_iae_log_visit(client, settings, view_name):
    institution = InstitutionWithMembershipFactory(kind="DREETS IAE")
    user = institution.members.get()

    settings.STATS_PH_PRESCRIPTION_REGION_WHITELIST = [institution.region]
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
            datetime(2023, 3, 10, tzinfo=UTC),
        ),
    )


@freeze_time("2023-03-10")
@override_settings(METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar")
@pytest.mark.parametrize(
    "view_name",
    [p.name for p in stats_urls.urlpatterns if p.name.startswith("stats_dgefp_")],
)
def test_stats_dgefp_log_visit(client, view_name):
    institution = InstitutionWithMembershipFactory(kind=InstitutionKind.DGEFP_IAE)
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
            datetime(2023, 3, 10, tzinfo=UTC),
        ),
    )


@freeze_time("2023-03-10")
@override_settings(METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar")
@pytest.mark.parametrize(
    "view_name",
    [p.name for p in stats_urls.urlpatterns if p.name.startswith("stats_dihal_")],
)
def test_stats_dihal_log_visit(client, view_name):
    institution = InstitutionWithMembershipFactory(kind="DIHAL")
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
            datetime(2023, 3, 10, tzinfo=UTC),
        ),
    )


@freeze_time("2023-03-10")
@override_settings(METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar")
@pytest.mark.parametrize(
    "view_name",
    [p.name for p in stats_urls.urlpatterns if p.name.startswith("stats_drihl_")],
)
def test_stats_drihl_log_visit(client, view_name):
    institution = InstitutionWithMembershipFactory(kind="DRIHL")
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
            datetime(2023, 3, 10, tzinfo=UTC),
        ),
    )


@freeze_time("2023-03-10")
@override_settings(METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar")
@pytest.mark.parametrize(
    "view_name",
    [p.name for p in stats_urls.urlpatterns if p.name.startswith("stats_iae_network_")],
)
def test_stats_iae_network_log_visit(client, view_name):
    institution = InstitutionWithMembershipFactory(kind="Réseau IAE")
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
            datetime(2023, 3, 10, tzinfo=UTC),
        ),
    )


def test_get_params_aci_asp_ids_for_department():
    company = CompanyFactory(kind=CompanyKind.ACI, department=factory.fuzzy.FuzzyChoice([31, 84]))
    assert get_params_aci_asp_ids_for_department(company.department) == {
        "id_asp_de_la_siae": [company.convention.asp_id]
    }
    assert get_params_aci_asp_ids_for_department(42) == {"id_asp_de_la_siae": []}


def test_get_params_aci_asp_ids_for_department_when_only_the_antenna_is_in_the_department():
    company = CompanyFactory(kind=CompanyKind.ACI, department=42)
    antenna = CompanyFactory(
        kind=CompanyKind.ACI,
        department=factory.fuzzy.FuzzyChoice([31, 84]),
        convention=company.convention,
        source=Company.SOURCE_USER_CREATED,
    )
    assert get_params_aci_asp_ids_for_department(antenna.department) == {"id_asp_de_la_siae": []}
    assert get_params_aci_asp_ids_for_department(company.department) == {
        "id_asp_de_la_siae": [company.convention.asp_id]
    }
