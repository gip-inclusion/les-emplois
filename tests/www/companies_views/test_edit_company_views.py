from django.urls import reverse
from pytest_django.asserts import assertContains, assertRedirects

from itou.companies.models import Company
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_NO_RESULT_MOCK, BAN_GEOCODING_API_RESULT_MOCK
from tests.companies.factories import (
    CompanyFactory,
)


def test_edit(client, mocker):
    mocker.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    company = CompanyFactory(with_membership=True)
    user = company.members.first()

    client.force_login(user)

    url = reverse("companies_views:edit_company_step_contact_infos")
    response = client.get(url)
    assertContains(response, "Informations générales")

    post_data = {
        "brand": "NEW FAMOUS COMPANY BRAND NAME",
        "phone": "0610203050",
        "email": "toto@titi.fr",
        "website": "https://famous-company.com",
        "address_line_1": "1 Rue Jeanne d'Arc",
        "address_line_2": "",
        "post_code": "62000",
        "city": "",
    }
    response = client.post(url, data=post_data)

    # Ensure form validation is done
    assertContains(response, "Ce champ est obligatoire")

    # Go to next step: description
    post_data["city"] = "Arras"
    response = client.post(url, data=post_data)
    assertRedirects(response, reverse("companies_views:edit_company_step_description"))

    response = client.post(url, data=post_data, follow=True)
    assertContains(response, "Présentation de l'activité")

    # Go to next step: summary and check the rendered markdown
    url = response.redirect_chain[-1][0]
    post_data = {
        # HTML tags should be ignored
        "description": "*Lorem ipsum*\n\n* list 1\n* list 2\n\n1. list 1\n2. list 2\n<h1>Gros titre</h1>",
        "provided_support": "On est très très forts pour [**tout**](https://simple.wikipedia.org/wiki/42_(answer))",
    }
    response = client.post(url, data=post_data)
    assertRedirects(response, reverse("companies_views:edit_company_step_preview"))

    response = client.post(url, data=post_data, follow=True)
    attrs = 'target="_blank" rel="noopener" aria-label="Ouverture dans un nouvel onglet"'
    assertContains(response, "Aperçu de la fiche")
    assertContains(
        response,
        (
            "<p><em>Lorem ipsum</em></p>\n<ul>\n<li>list 1</li>\n<li>list 2</li>\n</ul>"
            "\n<ol>\n<li>list 1</li>\n<li>list 2</li>\n</ol>\n\nGros titre"
        ),
    )
    assertContains(
        response,
        (
            "<p>On est très très forts pour "
            f'<a href="https://simple.wikipedia.org/wiki/42_(answer)" {attrs}><strong>tout</strong></a></p>'
        ),
    )

    # Go back, should not be an issue
    step_2_url = reverse("companies_views:edit_company_step_description")
    response = client.get(step_2_url)
    assertContains(response, "Présentation de l'activité")
    assert client.session["edit_siae_session_key"] == {
        "address_line_1": "1 Rue Jeanne d'Arc",
        "address_line_2": "",
        "brand": "NEW FAMOUS COMPANY BRAND NAME",
        "city": "Arras",
        "department": "62",
        "description": "*Lorem ipsum*\n\n* list 1\n* list 2\n\n1. list 1\n2. list 2\n<h1>Gros titre</h1>",
        "email": "toto@titi.fr",
        "phone": "0610203050",
        "post_code": "62000",
        "provided_support": "On est très très forts pour [**tout**](https://simple.wikipedia.org/wiki/42_(answer))",
        "website": "https://famous-company.com",
    }

    # Go forward again
    response = client.post(step_2_url, data=post_data, follow=True)
    attrs = 'target="_blank" rel="noopener" aria-label="Ouverture dans un nouvel onglet"'
    assertContains(response, "Aperçu de la fiche")
    assertContains(
        response,
        (
            "<p>On est très très forts pour "
            f'<a href="https://simple.wikipedia.org/wiki/42_(answer)" {attrs}><strong>tout</strong></a></p>'
        ),
    )

    # Save the object for real
    response = client.post(response.redirect_chain[-1][0])
    assertRedirects(response, reverse("dashboard:index"))

    # refresh company, but using the siret to be sure we didn't mess with the PK
    company = Company.objects.get(siret=company.siret)

    assert company.brand == "NEW FAMOUS COMPANY BRAND NAME"
    assert company.description == "*Lorem ipsum*\n\n* list 1\n* list 2\n\n1. list 1\n2. list 2\n<h1>Gros titre</h1>"
    assert company.email == "toto@titi.fr"
    assert company.phone == "0610203050"
    assert company.website == "https://famous-company.com"

    assert company.address_line_1 == "1 Rue Jeanne d'Arc"
    assert company.address_line_2 == ""
    assert company.post_code == "62000"
    assert company.city == "Arras"
    assert company.department == "62"

    # This data comes from BAN_GEOCODING_API_RESULT_MOCK.
    assert company.coords == "SRID=4326;POINT (2.316754 48.838411)"
    assert company.latitude == 48.838411
    assert company.longitude == 2.316754
    assert company.geocoding_score == 0.5197687103594081


def test_permission(client):
    company = CompanyFactory(with_membership=True)
    user = company.members.first()

    client.force_login(user)

    # Only admin members should be allowed to edit company's details
    membership = user.companymembership_set.first()
    membership.is_admin = False
    membership.save()
    url = reverse("companies_views:edit_company_step_contact_infos")
    response = client.get(url)
    assert response.status_code == 403


def test_edit_with_wrong_address(client, mocker):
    mocker.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_NO_RESULT_MOCK)
    company = CompanyFactory(with_membership=True)
    user = company.members.first()

    client.force_login(user)

    url = reverse("companies_views:edit_company_step_contact_infos")
    response = client.get(url)
    assertContains(response, "Informations générales")

    post_data = {
        "brand": "NEW FAMOUS COMPANY BRAND NAME",
        "phone": "0610203050",
        "email": "toto@titi.fr",
        "website": "https://famous-company.com",
        "address_line_1": "1 Rue Jeanne d'Arc",
        "address_line_2": "",
        "post_code": "62000",
        "city": "Arras",
    }
    response = client.post(url, data=post_data, follow=True)

    assertRedirects(response, reverse("companies_views:edit_company_step_description"))

    # Go to next step: summary
    url = response.redirect_chain[-1][0]
    post_data = {
        "description": "Le meilleur des SIAEs !",
        "provided_support": "On est très très forts pour tout",
    }
    response = client.post(url, data=post_data, follow=True)
    assertRedirects(response, reverse("companies_views:edit_company_step_preview"))

    # Save the object for real
    response = client.post(response.redirect_chain[-1][0])
    assertContains(response, "L'adresse semble erronée")
