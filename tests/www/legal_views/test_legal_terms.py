import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.utils.legal_terms import get_latest_terms_datetime, get_terms_versions
from tests.users.factories import EmployerFactory
from tests.utils.testing import parse_response_to_soup


CGU_FORM_BTN = "J'accepte</button>"


def test_legal_terms_post_updates_timestamp_when_acceptance_required(client):
    user = EmployerFactory(membership=True, terms_accepted_at=None)
    client.force_login(user)

    response = client.get(reverse("legal-terms"))
    assertContains(response, CGU_FORM_BTN)
    assertContains(response, 'name="terms_slug" required>')  # the checkbox is mandatory

    next_url = reverse("dashboard:edit_user_info")
    with freeze_time("2024-02-19T10:00:00+01:00"):
        latest_terms = get_terms_versions()[0]
        response = client.post(
            reverse("legal-terms"),
            data={"next": next_url, "terms_slug": latest_terms.slug},
        )

    assertRedirects(response, next_url, fetch_redirect_response=False)
    user.refresh_from_db()
    assert user.terms_accepted_at == datetime.datetime(2024, 2, 19, 10, 0, tzinfo=ZoneInfo(settings.TIME_ZONE))


def test_legal_terms_post_updates_timestamp_when_accepted_terms_are_outdated(client):
    latest_terms_datetime = get_latest_terms_datetime()
    terms_accepted_at = latest_terms_datetime - datetime.timedelta(days=1)
    user = EmployerFactory(membership=True, terms_accepted_at=terms_accepted_at)
    client.force_login(user)
    next_url = reverse("dashboard:edit_user_info")

    latest_terms = get_terms_versions()[0]
    # the user submits the form at the exact moment a new version is published
    with freeze_time(latest_terms_datetime):
        response = client.post(
            reverse("legal-terms"),
            data={"next": next_url, "terms_slug": latest_terms.slug},
        )

    assertRedirects(response, next_url, fetch_redirect_response=False)
    user.refresh_from_db()
    assert user.terms_accepted_at == latest_terms_datetime


@pytest.mark.parametrize(
    "slug,date,content",  # 'content' should be a string exclusive to each version
    [
        ("2022-10-14", "14/10/2022", "« L’Employeur solidaire »"),
        ("2024-02-05", "05/02/2024", "« L’Employeur inclusif »"),
        ("2025-10-15", "15/10/2025", "« Le bénéficiaire du parcours »"),
        ("2026-03-16", "16/03/2026", "bilan d’exécution annuel validé par sa DDETS et DREETS"),
    ],
)
def test_previous_legal_terms_versions_are_accessible_and_public(client, slug, date, content):
    response = client.get(reverse("legal-terms-version", kwargs={"version_slug": slug}))
    assertNotContains(response, CGU_FORM_BTN)
    assertContains(response, f"Version du {date}")
    assertContains(response, content)
    if slug == "2026-03-16":
        assertContains(response, "vous consultez la dernière version")
    else:
        assertContains(response, "version actuellement consultée")
        assertContains(response, "dernière version")


def test_legal_terms_page_uses_latest_version_and_is_public(client):
    latest = get_terms_versions()[0]
    response = client.get(reverse("legal-terms"))
    assertNotContains(response, CGU_FORM_BTN)
    assertContains(response, f"En vigueur à partir du {latest.date.strftime('%d/%m/%Y')}")
    assertContains(response, "vous consultez la dernière version")


def test_legal_terms_version_raises_404_for_unknown_slug(client):
    response = client.get(reverse("legal-terms-version", kwargs={"version_slug": "1900-01-01"}))
    assert response.status_code == 404


def test_legal_terms_post_with_wrong_terms_slug_displays_a_message(client):
    """Edge case where the user submits the acceptance form with an outdated slug.

    This can happen when the terms were updated while they had the form open...
    In this rare case, the user lands back on the form but with the very latest terms version.
    """
    user = EmployerFactory(membership=True, terms_accepted_at=None)
    client.force_login(user)
    response = client.post(
        reverse("legal-terms"),
        data={"next": reverse("dashboard:index"), "terms_slug": "2021-02-24"},
    )
    assertContains(response, CGU_FORM_BTN)
    msg = "Une nouvelle version des Conditions Générales d’Utilisation vient d'entrer en vigueur."
    assert parse_response_to_soup(response, selector=".s-title-02 .alert").text.strip() == msg
    user.refresh_from_db()
    assert user.terms_accepted_at is None
