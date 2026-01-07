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
from itou.prescribers.enums import DGFT_SAFIR_CODE, PrescriberOrganizationKind
from itou.utils.apis import metabase as mb
from itou.utils.apis.metabase import METABASE_DASHBOARDS
from itou.www.stats import urls as stats_urls, utils as stats_utils
from itou.www.stats.views import get_params_aci_asp_ids_for_department
from tests.companies.factories import CompanyFactory
from tests.institutions.factories import InstitutionFactory
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import ItouStaffFactory, PrescriberFactory


class TestStatsView:
    @override_settings(METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar")
    def test_stats_public(self, client):
        url = reverse("stats:stats_public")
        response = client.get(url)
        assert response.status_code == 200

    @override_settings(METABASE_SITE_URL=None, METABASE_SECRET_KEY=None)
    def test_stats_public_empty_settings(self, client):
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
    prescriber_org = PrescriberOrganizationFactory(
        kind=PrescriberOrganizationKind.FT, authorized=True, with_membership=True
    )
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
    prescriber_org = PrescriberOrganizationFactory(kind="DEPT", authorized=True, department="22", with_membership=True)
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
    institution = InstitutionFactory(kind="DDETS IAE", department="22", with_membership=True)
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
    [p.name for p in stats_urls.urlpatterns if p.name.startswith("stats_ddets_log_")],
)
def test_stats_ddets_log_log_visit(client, settings, view_name):
    institution = InstitutionFactory(kind="DDETS LOG", with_membership=True)
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
    institution = InstitutionFactory(kind="DREETS IAE", department="22", with_membership=True)
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
    institution = InstitutionFactory(kind=InstitutionKind.DGEFP_IAE, with_membership=True)
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
    institution = InstitutionFactory(kind="DIHAL", with_membership=True)
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
    institution = InstitutionFactory(kind="DRIHL", with_membership=True)
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
    institution = InstitutionFactory(kind="Réseau IAE", with_membership=True)
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
def test_stats_staff(client):
    # Login required
    view_name = "stats_staff_service_indicators"
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


@override_settings(
    METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar", TALLY_URL="http://tally.fake"
)
def test_suspended_stats_page_banner(client, snapshot):
    """Test a banner appears for the user when a dashboard is marked as suspended"""
    client.force_login(ItouStaffFactory())
    staff_dashboard_id = METABASE_DASHBOARDS.get("stats_staff_service_indicators")["dashboard_id"]
    tally_suspension_form = f"http://tally.fake/r/wkOxRR?URLTB={staff_dashboard_id}"

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
    institution = InstitutionFactory(kind=institution_kind, with_membership=True)
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
    organization = PrescriberOrganizationFactory(
        kind=organization_kind, department="75", authorized=True, with_membership=True
    )
    client.force_login(organization.members.get())

    response = client.get(reverse("stats:stats_ph_state_main"))
    assert response.status_code == 200
    assert response.context["tally_hidden_fields"] == {"type_prescripteur": organization_kind}


@pytest.fixture
def ft_agencies_for_stats_ph_raw(db):
    for dept in ["04", "05", "13", "83"]:  # PACA
        PrescriberOrganizationFactory(kind=PrescriberOrganizationKind.FT, department=dept, authorized=True)
    for dept in ["75", "92"]:  # IDF
        PrescriberOrganizationFactory(kind=PrescriberOrganizationKind.FT, department=dept, authorized=True)


@pytest.mark.parametrize(
    "org_kind,department,code_safir,expected_count",
    [
        pytest.param(PrescriberOrganizationKind.FT, "75", DGFT_SAFIR_CODE, 7, id="dgft"),  # All FT + self
        pytest.param(PrescriberOrganizationKind.FT, "13", "13992", 5, id="drft"),  # PACA FT + self
        pytest.param(PrescriberOrganizationKind.FT, "04", "04016", 3, id="dtft"),  # Depts 04/05 + self
        pytest.param(PrescriberOrganizationKind.FT, "75", "12345", 1, id="normal_ft"),  # Only self
        pytest.param(PrescriberOrganizationKind.ML, "75", None, 1, id="non_ft"),  # Only self
    ],
)
@override_settings(METABASE_SITE_URL="http://metabase.fake", METABASE_SECRET_KEY="foobar")
def test_stats_ph_raw_prescriber_org_pks(
    client,
    mocker,
    ft_agencies_for_stats_ph_raw,
    org_kind,
    department,
    code_safir,
    expected_count,
):
    from itou.www.stats import views as stats_views

    spy_render_stats_ph = mocker.spy(stats_views, "render_stats_ph")

    org = PrescriberOrganizationFactory(
        kind=org_kind,
        department=department,
        code_safir_pole_emploi=code_safir,
        authorized=True,
        with_membership=True,
    )
    client.force_login(org.members.get())

    response = client.get(reverse("stats:stats_ph_raw"))
    assert response.status_code == 200

    spy_render_stats_ph.assert_called_once()
    extra_params = spy_render_stats_ph.call_args.kwargs["extra_params"]
    assert mb.C1_PRESCRIBER_ORG_FILTER_KEY in extra_params
    pk_list = extra_params[mb.C1_PRESCRIBER_ORG_FILTER_KEY]
    assert len(pk_list) == expected_count
    assert org.pk in pk_list
