import datetime
from http import HTTPStatus
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains

from itou.utils.legal_terms import get_latest_terms_datetime, get_terms_versions
from tests.users.factories import EmployerFactory


def test_legal_terms_post_updates_timestamp_when_acceptance_required(client, mocker):
    user = EmployerFactory(membership=True, terms_accepted_at=None)
    set_terms_accepted_spy = mocker.spy(user.__class__, "set_terms_accepted")
    client.force_login(user)

    response = client.get(reverse("legal-terms"))
    assertContains(response, "cgu-acceptance-form")
    assertContains(response, "J'accepte")
    assertContains(response, "disabled")

    next_url = reverse("dashboard:edit_user_info")
    with freeze_time("2024-02-19T10:00:00+01:00"):
        latest_terms = get_terms_versions()[-1]
        response = client.post(
            reverse("legal-terms"),
            data={REDIRECT_FIELD_NAME: next_url, "terms_slug": latest_terms.slug},
        )

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == next_url
    set_terms_accepted_spy.assert_called_once()
    assert set_terms_accepted_spy.call_args.args[0].pk == user.pk
    user.refresh_from_db()
    assert user.terms_accepted_at == datetime.datetime(2024, 2, 19, 10, 0, tzinfo=ZoneInfo(settings.TIME_ZONE))


def test_legal_terms_post_updates_timestamp_when_accepted_terms_are_outdated(client, mocker):
    latest_terms_datetime = get_latest_terms_datetime()
    terms_accepted_at = latest_terms_datetime - datetime.timedelta(days=1)
    user = EmployerFactory(membership=True, terms_accepted_at=terms_accepted_at)
    set_terms_accepted_spy = mocker.spy(user.__class__, "set_terms_accepted")
    client.force_login(user)
    next_url = reverse("dashboard:edit_user_info")

    latest_terms = get_terms_versions()[-1]
    with freeze_time(get_latest_terms_datetime() + datetime.timedelta(days=1)):
        response = client.post(
            reverse("legal-terms"),
            data={REDIRECT_FIELD_NAME: next_url, "terms_slug": latest_terms.slug},
        )

    assert response.status_code == HTTPStatus.FOUND
    assert response.url == next_url
    set_terms_accepted_spy.assert_called_once()
    assert set_terms_accepted_spy.call_args.args[0].pk == user.pk
    user.refresh_from_db()
    assert user.terms_accepted_at == get_latest_terms_datetime() + datetime.timedelta(days=1)


@pytest.mark.parametrize(
    "slug,date,content",
    [
        ("2022-10-14", "14/10/2022", "« L’Employeur solidaire »"),
        ("2024-02-05", "05/02/2024", "« L’Employeur inclusif »"),
        ("2025-10-15", "15/10/2025", "« Le bénéficiaire du parcours »"),
    ],
)
def test_previous_legal_terms_versions_are_accessible_and_public(client, slug, date, content):
    response = client.get(reverse("legal-terms-version", kwargs={"version_slug": slug}))
    assertNotContains(response, "cgu-acceptance-form")
    assertContains(response, f"Version du {date}")
    assertContains(response, content)
    if slug == "2025-10-15":
        assertContains(response, "vous consultez la dernière version")
    else:
        assertContains(response, "version actuellement consultée")
        assertContains(response, "dernière version")


def test_legal_terms_page_uses_latest_version_and_is_public(client):
    latest = get_terms_versions()[-1]
    response = client.get(reverse("legal-terms"))
    assertNotContains(response, "cgu-acceptance-form")
    assertContains(response, f"En vigueur à partir du {latest.date.strftime('%d/%m/%Y')}")
    assertContains(response, "vous consultez la dernière version")


def test_legal_terms_version_raises_404_for_unknown_slug(client):
    response = client.get(reverse("legal-terms-version", kwargs={"version_slug": "1900-01-01"}))
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_legal_terms_post_with_wrong_terms_slug_does_nothing(client):
    """Edge case where the user submits the acceptance form with an outdated slug.

    This can happen when the terms were updated while they had the form open...
    In this rare case, the user lands back on the form but with the very latest terms version.
    """
    user = EmployerFactory(membership=True, terms_accepted_at=None)
    client.force_login(user)
    response = client.post(
        reverse("legal-terms"),
        data={REDIRECT_FIELD_NAME: reverse("dashboard:index"), "terms_slug": "2021-02-24"},
    )
    assertContains(response, "cgu-acceptance-form")
    user.refresh_from_db()
    assert user.terms_accepted_at is None
