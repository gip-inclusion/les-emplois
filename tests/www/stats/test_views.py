from datetime import UTC, datetime
from unittest.mock import patch

import factory
import pytest
from django.test import override_settings
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertQuerySetEqual, assertRedirects

from itou.analytics.models import StatsDashboardVisit
from itou.common_apps.address.departments import DEPARTMENT_TO_REGION
from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from itou.institutions.enums import InstitutionKind
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.utils.apis.metabase import METABASE_DASHBOARDS
from itou.www.stats import urls as stats_urls, utils as stats_utils
from itou.www.stats.views import get_params_aci_asp_ids_for_department
from tests.companies.factories import CompanyFactory
from tests.institutions.factories import InstitutionWithMembershipFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import ItouStaffFactory, PrescriberFactory


class TestStatsView:
    @override_settings(METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar")
    def test_stats_public(self, client):
        url = reverse("stats:stats_public")
        response = client.get(url)
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
    [p.name for p in stats_urls.urlpatterns if p.name.startswith("stats_ft_")],
)
def test_stats_ft_log_visit(client, view_name):
    prescriber_org = PrescriberOrganizationWithMembershipFactory(kind=PrescriberOrganizationKind.FT, authorized=True)
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
    prescriber_org = PrescriberOrganizationWithMembershipFactory(kind="DEPT", authorized=True, department="22")
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
    [p.name for p in stats_urls.urlpatterns if p.name.startswith("stats_siae_")],
)
def test_stats_siae_log_visit(client, settings, view_name):
    company = CompanyFactory(name="El garaje de la esperanza", kind="ACI", with_membership=True)
    user = company.members.get()

    settings.STATS_SIAE_USER_PK_WHITELIST = [user.pk]

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
    institution = InstitutionWithMembershipFactory(kind="DREETS IAE", department="22")
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
            datetime(2023, 3, 10, tzinfo=UTC),
        ),
    )


@freeze_time("2023-03-10")
@override_settings(METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar")
@pytest.mark.parametrize(
    "view_name",
    [
        p.name
        for p in stats_urls.urlpatterns
        if p.name.startswith("stats_dgefp_iae_") and p.name not in {"stats_dgefp_iae_showroom"}
    ],
)
def test_stats_dgefp_iae_log_visit(client, view_name):
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


@freeze_time("2023-03-10")
@override_settings(METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar")
@pytest.mark.parametrize(
    "view_name",
    ["stats_staff_service_indicators"],
)
def test_stats_staff(client, view_name):
    # Login required
    url = reverse(f"stats:{view_name}")
    response = client.get(url)
    assertRedirects(response, reverse("account_login") + f"?next={url}")

    user = ItouStaffFactory()
    client.force_login(user)
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
            None,
            user.kind,
            user.pk,
            datetime(2023, 3, 10, tzinfo=UTC),
        ),
    )


@override_settings(METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar")
def test_webinar_banner_display(client, snapshot):
    client.force_login(ItouStaffFactory())
    url = reverse("stats:stats_staff_service_indicators")

    with override_settings(PILOTAGE_SHOW_STATS_WEBINAR=True):
        response = client.get(url)
        assert response.status_code == 200
        rendered_banners = [
            banner | {"is_displayable": True} for banner in response.context["pilotage_webinar_banners"]
        ]
        assert str(rendered_banners) == snapshot

    with override_settings(PILOTAGE_SHOW_STATS_WEBINAR=False):
        response = client.get(url)
        assert response.status_code == 200
        assert response.context["pilotage_webinar_banners"] == []


@override_settings(METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar")
def test_suspended_stats_page_banner(client, snapshot):
    """Test a banner appears for the user when a dashboard is marked as suspended"""
    client.force_login(ItouStaffFactory())
    staff_dashboard_id = METABASE_DASHBOARDS.get("stats_staff_service_indicators")["dashboard_id"]
    tally_suspension_form = f"https://tally.so/r/wkOxRR?URLTB={staff_dashboard_id}"

    with patch("itou.utils.apis.metabase.SUSPENDED_DASHBOARD_IDS", [staff_dashboard_id]):
        response = client.get(reverse("stats:stats_staff_service_indicators"))
        assert response.status_code == 200
        assertContains(response, tally_suspension_form)

    with patch("itou.utils.apis.metabase.SUSPENDED_DASHBOARD_IDS", []):
        response = client.get(reverse("stats:stats_staff_service_indicators"))
        assert response.status_code == 200
        assertNotContains(response, tally_suspension_form)


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


@pytest.mark.parametrize("dashboard_name", ["ph_prescription", "state"])
@pytest.mark.parametrize(
    "institution_kind", [InstitutionKind.DGEFP_IAE, InstitutionKind.DREETS_IAE, InstitutionKind.DDETS_IAE]
)
@override_settings(METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar")
def test_stats_redirect_for_institution(client, institution_kind, dashboard_name):
    institution = InstitutionWithMembershipFactory(kind=institution_kind)
    client.force_login(institution.members.get())

    response = client.get(reverse("stats:redirect", kwargs={"dashboard_name": dashboard_name}), follow=True)
    assert response.status_code == 200


def test_stats_ph_state_main_for_prescriber_without_organization(client):
    client.force_login(PrescriberFactory())

    response = client.get(reverse("stats:stats_ph_state_main"))
    assert response.status_code == 403


@freeze_time("2023-03-10")
@override_settings(METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar")
@pytest.mark.parametrize("organization_kind", stats_utils.STATS_PH_ORGANISATION_KIND_WHITELIST)
def test_stats_ph_state_main_tally_form_overrides(client, organization_kind):
    organization = PrescriberOrganizationWithMembershipFactory(
        kind=organization_kind, department="75", authorized=True
    )
    client.force_login(organization.members.get())

    response = client.get(reverse("stats:stats_ph_state_main"))
    assert response.status_code == 200
    assert response.context["tally_hidden_fields"] == {"type_prescripteur": organization_kind}
