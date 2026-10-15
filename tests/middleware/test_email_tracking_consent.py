import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects, assertTemplateUsed

from itou.utils.legal_terms import get_terms_versions
from tests.companies.factories import CompanyFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory
from tests.www.apply.test_submit import fake_session_initialization


@pytest.mark.parametrize("factory", [EmployerFactory, JobSeekerFactory])
@pytest.mark.parametrize("url_name", ["dashboard:api_token", "dashboard:index"])
def test_middleware_redirects_users_who_never_answered(client, factory, url_name):
    client.force_login(factory(email_tracking_consent_updated_at=None))
    target_url = reverse(url_name)
    response = client.get(target_url)
    expected_url = reverse("dashboard:email_tracking_consent", query={"next": target_url})
    assertRedirects(response, expected_url=expected_url, fetch_redirect_response=False)


def test_middleware_is_switched_off(client, settings):
    settings.REQUIRE_EMAIL_TRACKING_CONSENT = False
    client.force_login(EmployerFactory(email_tracking_consent_updated_at=None))
    response = client.get(reverse("dashboard:index"))
    assertTemplateUsed(response, "dashboard/dashboard.html")


@pytest.mark.parametrize("consent", [True, False])
def test_middleware_lets_users_who_answered_through(client, consent):
    client.force_login(EmployerFactory(email_tracking_consent=consent))
    response = client.get(reverse("dashboard:index"))
    assertTemplateUsed(response, "dashboard/dashboard.html")


def test_middleware_allows_htmx_requests(client):
    client.force_login(EmployerFactory(email_tracking_consent_updated_at=None))
    response = client.get(reverse("dashboard:index"), headers={"HX-Request": "true"})
    assertTemplateUsed(response, "dashboard/dashboard.html")


def test_middleware_allows_post_requests(client):
    client.force_login(EmployerFactory(email_tracking_consent_updated_at=None))
    response = client.post(reverse("dashboard:edit_user_info"))
    assertTemplateUsed(response, "dashboard/edit_user_info.html")


@pytest.mark.parametrize(
    "url_name, expected_content",
    [
        ("accessibility", "Déclaration d'accessibilité"),
        ("legal-privacy", "Politique de confidentialité"),
        ("dashboard:edit_user_notifications", "Mes notifications"),
    ],
)
def test_middleware_allows_public_and_exempted_pages(client, url_name, expected_content):
    client.force_login(JobSeekerFactory(email_tracking_consent_updated_at=None))
    response = client.get(reverse(url_name))
    assertContains(response, f"<h1>{expected_content}</h1>", html=True)


def test_middleware_allows_api(client):
    client.force_login(EmployerFactory(email_tracking_consent_updated_at=None))
    # DRF views don’t require a login, so they are let through anyway: this one is a plain Django view
    response = client.get(reverse("v1:rest_framework:logout"))
    assert response.status_code == 405


def test_middleware_brings_job_seekers_back_to_the_apply_tunnel(client):
    company = CompanyFactory(with_jobs=True, with_membership=True)
    job_seeker = JobSeekerFactory(email_tracking_consent_updated_at=None)
    client.force_login(job_seeker)
    apply_session = fake_session_initialization(client, company, job_seeker, {"selected_jobs": []})
    step_url = reverse("apply:application_jobs", kwargs={"session_uuid": apply_session.name})

    response = client.get(step_url)
    consent_url = reverse("dashboard:email_tracking_consent", query={"next": step_url})
    assertRedirects(response, consent_url, fetch_redirect_response=False)

    response = client.post(consent_url, data={"refuse": "1"})
    assertRedirects(response, step_url, fetch_redirect_response=False)
    response = client.get(step_url)
    assertTemplateUsed(response, "apply/submit/application/jobs.html")


def test_terms_come_first_then_email_tracking_consent(client):
    user = EmployerFactory(terms_accepted_at=None, email_tracking_consent_updated_at=None)
    client.force_login(user)
    dashboard_url = reverse("dashboard:index")

    response = client.get(dashboard_url)
    assertRedirects(response, reverse("legal-terms", query={"next": dashboard_url}), fetch_redirect_response=False)
    # The consent page is not reachable before the terms are accepted
    response = client.get(reverse("dashboard:email_tracking_consent", query={"next": dashboard_url}))
    assertRedirects(response, dashboard_url, fetch_redirect_response=False)

    response = client.post(
        reverse("legal-terms"), data={"next": dashboard_url, "terms_slug": get_terms_versions()[0].slug}
    )
    assertRedirects(response, dashboard_url, fetch_redirect_response=False)
    response = client.get(dashboard_url)
    consent_url = reverse("dashboard:email_tracking_consent", query={"next": dashboard_url})
    assertRedirects(response, consent_url, fetch_redirect_response=False)

    response = client.post(consent_url, data={"email_tracking_consent": "on"})
    assertRedirects(response, dashboard_url, fetch_redirect_response=False)
    response = client.get(dashboard_url)
    assertTemplateUsed(response, "dashboard/dashboard.html")
