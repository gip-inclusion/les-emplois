import uuid
from urllib.parse import quote

import pytest
from django.conf import settings
from django.core.files.storage import storages
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplication
from tests.cities.factories import create_city_guerande, create_city_vannes
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory, JobDescriptionFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.jobs.factories import create_test_romes_and_appellations
from tests.utils.test import parse_response_to_soup


INTERNAL_TRANSFER_CONFIRM_BUTTON = """
<button type="submit" class="btn btn-block btn-primary" aria-label="Passer à l’étape suivante">
    <span>Confirmer</span>
</button>"""

PREVIOUS_RESUME_TEXT = "Souhaitez-vous conserver le CV présent dans la candidature d’origine ?"


def test_anonymous_access(client):
    job_application = JobApplicationFactory()
    for viewname in (
        "apply:job_application_external_transfer_step_1",
        "apply:job_application_external_transfer_step_end",
    ):
        url = reverse(viewname, kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    company = CompanyFactory(with_jobs=True, with_membership=True)
    for viewname in (
        "apply:job_application_external_transfer_step_2",
        "apply:job_application_external_transfer_step_3",
        "apply:job_application_internal_transfer",
    ):
        url = reverse(viewname, kwargs={"job_application_id": job_application.pk, "company_pk": company.pk})
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")


@pytest.mark.parametrize("state", JobApplicationState)
def test_step_1_status_checks(client, state):
    job_application = JobApplicationFactory(state=state)
    employer = job_application.to_company.members.get()
    client.force_login(employer)
    response = client.get(
        reverse("apply:job_application_external_transfer_step_1", kwargs={"job_application_id": job_application.pk})
        + "?city={job_application.to_company.city_slug}"
    )
    assert response.status_code == (200 if state == JobApplicationState.REFUSED else 404)


def test_step_1(client, snapshot):
    create_test_romes_and_appellations(["N1101"], appellations_per_rome=1)
    vannes = create_city_vannes()
    COMPANY_VANNES = "Entreprise Vannes"
    other_company = CompanyFactory(name=COMPANY_VANNES, coords=vannes.coords, post_code="56760", with_membership=True)
    job = JobDescriptionFactory(company=other_company)

    guerande = create_city_guerande()
    COMPANY_GUERANDE = "Entreprise Guérande"
    CompanyFactory(name=COMPANY_GUERANDE, coords=guerande.coords, post_code="44350")

    job_application = JobApplicationFactory(
        state=JobApplicationState.REFUSED,
        for_snapshot=True,
        to_company__post_code="56760",
        to_company__coords=vannes.coords,
        to_company__city=vannes.name,
    )
    employer = job_application.to_company.members.get()
    client.force_login(employer)

    # Go th step 1
    transfer_step_1_url = reverse(
        "apply:job_application_external_transfer_step_1", kwargs={"job_application_id": job_application.pk}
    )
    response = client.get(transfer_step_1_url, follow=True)
    assertRedirects(response, transfer_step_1_url + "?city=vannes-56")
    assert str(parse_response_to_soup(response, ".c-stepper")) == snapshot(name="progress")

    # search is centered on job app company city : only vannes companies should be displayed
    assertContains(
        response,
        '<p class="mb-0"><strong>2 résultats</strong></p>',
        html=True,
        count=1,
    )
    assertContains(response, other_company.name.capitalize())
    assertContains(response, job_application.to_company.name.capitalize())
    assertNotContains(response, "Postuler")
    assertContains(
        response,
        "<span>Transférer la candidature</span>",
        count=2,
    )

    # Check outgoing links
    transfer_step_2_base_url = reverse(
        "apply:job_application_external_transfer_step_2",
        kwargs={"job_application_id": job_application.pk, "company_pk": other_company.pk},
    )
    assertContains(
        response,
        f"{transfer_step_2_base_url}?back_url={quote(transfer_step_1_url)}",
        count=1,
    )

    company_card_url = (
        reverse(
            "apply:job_application_external_transfer_step_1_company_card",
            kwargs={"job_application_id": job_application.pk, "company_pk": other_company.pk},
        )
        + f"?back_url={quote(transfer_step_1_url)}"
    )
    assertContains(response, company_card_url, count=1)

    job_card_url = (
        reverse(
            "apply:job_application_external_transfer_step_1_job_description_card",
            kwargs={"job_application_id": job_application.pk, "job_description_id": job.pk},
        )
        + f"?back_url={quote(transfer_step_1_url)}"
    )
    assertContains(response, job_card_url, count=1)

    # Check company card
    response = client.get(company_card_url)
    assert str(parse_response_to_soup(response, ".c-stepper")) == snapshot(name="progress")
    assertContains(
        response,
        f"{transfer_step_2_base_url}?back_url={quote(company_card_url)}",
        count=2,
    )
    assertContains(response, job_card_url, count=1)
    assertNotContains(response, "Postuler")
    assertContains(
        response,
        "<span>Transférer la candidature</span>",
        count=2,
    )

    # Check job description card
    response = client.get(job_card_url)
    assert str(parse_response_to_soup(response, ".c-stepper")) == snapshot(name="progress")
    assertContains(
        response,
        f"{transfer_step_2_base_url}?job_description_id={job.pk}&back_url={quote(job_card_url)}",
        count=1,
    )
    assertContains(response, company_card_url, count=1)
    assertNotContains(response, "Postuler")
    assertContains(
        response,
        "<span>Transférer la candidature</span>",
        count=1,
    )


def test_step_2_same_company(client):
    job_application = JobApplicationFactory(state=JobApplicationState.REFUSED, for_snapshot=True)
    company = job_application.to_company
    client.force_login(company.members.get())

    transfer_step_1_url = reverse(
        "apply:job_application_external_transfer_step_1", kwargs={"job_application_id": job_application.pk}
    )
    transfer_step_2_base_url = reverse(
        "apply:job_application_external_transfer_step_2",
        kwargs={"job_application_id": job_application.pk, "company_pk": job_application.to_company.pk},
    )
    transfer_step_2_url = f"{transfer_step_2_base_url}?back_url={quote(transfer_step_1_url)}"
    response = client.get(transfer_step_2_url, follow=True)

    internal_transfer_url = reverse(
        "apply:job_application_internal_transfer",
        kwargs={"job_application_id": job_application.pk, "company_pk": job_application.to_company.pk},
    )
    assertRedirects(response, f"{internal_transfer_url}?back_url={quote(transfer_step_1_url, safe='')}")
    assertNotContains(response, INTERNAL_TRANSFER_CONFIRM_BUTTON, html=True)
    assertContains(response, "<h1>Transfert impossible</h1>")

    # Check transfer view raises a 404
    internal_transfer_post_url = reverse("apply:transfer", kwargs={"job_application_id": job_application.pk})
    response = client.post(
        internal_transfer_post_url,
        data={"target_company_id": job_application.to_company.pk},
        follow=True,
    )
    assertContains(response, "Une erreur est survenue lors du transfert de la candidature")

    job_application.refresh_from_db()
    assert job_application.state == JobApplicationState.REFUSED


def test_step_2_internal_transfer(client):
    job_application = JobApplicationFactory(state=JobApplicationState.REFUSED, for_snapshot=True)
    employer = job_application.to_company.members.get()
    other_company = CompanyMembershipFactory(user=employer).company
    client.force_login(employer)

    transfer_step_1_url = reverse(
        "apply:job_application_external_transfer_step_1", kwargs={"job_application_id": job_application.pk}
    )
    transfer_step_2_base_url = reverse(
        "apply:job_application_external_transfer_step_2",
        kwargs={"job_application_id": job_application.pk, "company_pk": other_company.pk},
    )
    transfer_step_2_url = f"{transfer_step_2_base_url}?back_url={quote(transfer_step_1_url)}"
    response = client.get(transfer_step_2_url, follow=True)

    internal_transfer_url = reverse(
        "apply:job_application_internal_transfer",
        kwargs={"job_application_id": job_application.pk, "company_pk": other_company.pk},
    )
    assertRedirects(response, f"{internal_transfer_url}?back_url={quote(transfer_step_1_url, safe='')}")
    assertContains(response, INTERNAL_TRANSFER_CONFIRM_BUTTON, html=True)
    assertContains(response, "<h1>Confirmation du transfert</h1>")
    internal_transfer_post_url = reverse("apply:transfer", kwargs={"job_application_id": job_application.pk})
    assertContains(response, f'<form method="post" action="{internal_transfer_post_url}">')

    response = client.post(internal_transfer_post_url, data={"target_company_id": other_company.pk})
    job_application.refresh_from_db()
    assert job_application.state == JobApplicationState.NEW
    assert job_application.to_company == other_company


def test_step_2(client, snapshot):
    job_application = JobApplicationFactory(state=JobApplicationState.REFUSED, for_snapshot=True)
    employer = job_application.to_company.members.get()
    other_company = CompanyFactory(with_membership=True, with_jobs=True)
    job_id = other_company.job_description_through.first().pk
    client.force_login(employer)

    transfer_step_1_url = reverse(
        "apply:job_application_external_transfer_step_1", kwargs={"job_application_id": job_application.pk}
    )
    transfer_step_2_base_url = reverse(
        "apply:job_application_external_transfer_step_2",
        kwargs={"job_application_id": job_application.pk, "company_pk": other_company.pk},
    )

    # No selected job
    transfer_step_2_url = f"{transfer_step_2_base_url}?back_url={quote(transfer_step_1_url)}"
    response = client.get(transfer_step_2_url)

    assert str(parse_response_to_soup(response, ".c-stepper")) == snapshot(name="progress")
    assertContains(response, "<h2>Sélectionner les métiers recherchés</h2>", html=True)
    assert response.context["form"].initial == {"selected_jobs": [], "spontaneous_application": True}

    response = client.post(transfer_step_2_url, data={"spontaneous_application": "on"})
    transfer_step_3_base_url = reverse(
        "apply:job_application_external_transfer_step_3",
        kwargs={"job_application_id": job_application.pk, "company_pk": other_company.pk},
    )
    transfer_step_3_url = f"{transfer_step_3_base_url}?back_url={quote(transfer_step_2_url)}"
    assertRedirects(response, transfer_step_3_url)
    assert client.session[f"job_application-{other_company.pk}"] == {"selected_jobs": []}

    # With selected job
    transfer_step_2_url = (
        f"{transfer_step_2_base_url}?job_description_id={job_id}&back_url={quote(transfer_step_1_url)}"
    )
    response = client.get(transfer_step_2_url)

    assert str(parse_response_to_soup(response, ".c-stepper")) == snapshot(name="progress")
    assertContains(response, "<h2>Sélectionner les métiers recherchés</h2>", html=True)
    assert response.context["form"].initial == {"selected_jobs": [str(job_id)]}

    response = client.post(transfer_step_2_url, data={"selected_jobs": [job_id]})
    transfer_step_3_url = f"{transfer_step_3_base_url}?back_url={quote(transfer_step_2_url)}"
    assertRedirects(response, transfer_step_3_url)
    assert client.session[f"job_application-{other_company.pk}"] == {"selected_jobs": [job_id]}


@freeze_time("2024-07-15 11:52:23")
def test_step_3(client, snapshot):
    job_application = JobApplicationFactory(state=JobApplicationState.REFUSED, for_snapshot=True)
    employer = job_application.to_company.members.get()
    other_company = CompanyFactory(with_membership=True)
    client.force_login(employer)

    transfer_step_2_url = reverse(
        "apply:job_application_external_transfer_step_2",
        kwargs={"job_application_id": job_application.pk, "company_pk": other_company.pk},
    )
    transfer_step_3_base_url = reverse(
        "apply:job_application_external_transfer_step_3",
        kwargs={"job_application_id": job_application.pk, "company_pk": other_company.pk},
    )
    transfer_step_3_url = f"{transfer_step_3_base_url}?back_url={quote(transfer_step_2_url)}"
    response = client.get(transfer_step_3_url)

    assert str(parse_response_to_soup(response, ".c-stepper")) == snapshot(name="progress")
    expected_message = f"Le 15/07/2024 à 11h52, Pierre DUPONT a écrit :\n\n{job_application.message}"
    assert response.context["form"].initial["message"] == expected_message

    response = client.post(transfer_step_3_url, data={"message": expected_message, "keep_original_resume": "True"})
    new_job_application = JobApplication.objects.filter(to_company=other_company).get()
    assertRedirects(
        response,
        reverse(
            "apply:job_application_external_transfer_step_end", kwargs={"job_application_id": new_job_application.pk}
        ),
    )
    assert new_job_application.message == expected_message
    assert new_job_application.job_seeker == job_application.job_seeker
    assert new_job_application.sender == employer
    assert new_job_application.state == JobApplicationState.NEW
    assert new_job_application.resume_link == job_application.resume_link

    transfer_log = job_application.logs.last()
    assert transfer_log.transition == "external_transfer"
    assert transfer_log.user == employer
    assert transfer_log.target_company == other_company


def test_step_3_no_previous_CV(client, mocker, pdf_file):
    job_application = JobApplicationFactory(state=JobApplicationState.REFUSED, for_snapshot=True, resume_link="")
    employer = job_application.to_company.members.get()
    other_company = CompanyFactory(with_membership=True)
    client.force_login(employer)

    transfer_step_2_url = reverse(
        "apply:job_application_external_transfer_step_2",
        kwargs={"job_application_id": job_application.pk, "company_pk": other_company.pk},
    )
    transfer_step_3_base_url = reverse(
        "apply:job_application_external_transfer_step_3",
        kwargs={"job_application_id": job_application.pk, "company_pk": other_company.pk},
    )
    transfer_step_3_url = f"{transfer_step_3_base_url}?back_url={quote(transfer_step_2_url)}"
    response = client.get(transfer_step_3_url)
    assertNotContains(response, PREVIOUS_RESUME_TEXT)

    mocker.patch(
        "itou.www.apply.views.submit_views.uuid.uuid4",
        return_value=uuid.UUID("11111111-1111-1111-1111-111111111111"),
    )
    response = client.post(transfer_step_3_url, data={"message": "blah", "resume": pdf_file})
    new_job_application = JobApplication.objects.filter(to_company=other_company).get()
    assertRedirects(
        response,
        reverse(
            "apply:job_application_external_transfer_step_end",
            kwargs={"job_application_id": new_job_application.pk},
        ),
    )
    assert new_job_application.message == "blah"
    assert new_job_application.job_seeker == job_application.job_seeker
    assert new_job_application.sender == employer
    assert new_job_application.resume_link == (
        f"{settings.AWS_S3_ENDPOINT_URL}tests/{storages['public'].location}"
        f"/resume/11111111-1111-1111-1111-111111111111.pdf"
    )
    assert new_job_application.state == JobApplicationState.NEW


def test_step_3_remove_previous_CV(client):
    job_application = JobApplicationFactory(state=JobApplicationState.REFUSED, for_snapshot=True)
    assert job_application.resume_link
    employer = job_application.to_company.members.get()
    other_company = CompanyFactory(with_membership=True)
    client.force_login(employer)

    transfer_step_2_url = reverse(
        "apply:job_application_external_transfer_step_2",
        kwargs={"job_application_id": job_application.pk, "company_pk": other_company.pk},
    )
    transfer_step_3_base_url = reverse(
        "apply:job_application_external_transfer_step_3",
        kwargs={"job_application_id": job_application.pk, "company_pk": other_company.pk},
    )
    transfer_step_3_url = f"{transfer_step_3_base_url}?back_url={quote(transfer_step_2_url)}"
    response = client.get(transfer_step_3_url)
    assertContains(response, PREVIOUS_RESUME_TEXT)

    response = client.post(transfer_step_3_url, data={"message": "blah"})
    assert response.context["form"].errors == {"keep_original_resume": ["Ce champ est obligatoire."]}

    response = client.post(transfer_step_3_url, data={"message": "blah", "keep_original_resume": "False"})
    new_job_application = JobApplication.objects.filter(to_company=other_company).get()
    assertRedirects(
        response,
        reverse(
            "apply:job_application_external_transfer_step_end",
            kwargs={"job_application_id": new_job_application.pk},
        ),
    )
    assert new_job_application.message == "blah"
    assert new_job_application.job_seeker == job_application.job_seeker
    assert new_job_application.sender == employer
    assert new_job_application.resume_link == ""
    assert new_job_application.state == JobApplicationState.NEW


def test_step_3_replace_previous_CV(client, mocker, pdf_file):
    job_application = JobApplicationFactory(state=JobApplicationState.REFUSED, for_snapshot=True)
    assert job_application.resume_link
    employer = job_application.to_company.members.get()
    other_company = CompanyFactory(with_membership=True)
    client.force_login(employer)

    transfer_step_2_url = reverse(
        "apply:job_application_external_transfer_step_2",
        kwargs={"job_application_id": job_application.pk, "company_pk": other_company.pk},
    )
    transfer_step_3_base_url = reverse(
        "apply:job_application_external_transfer_step_3",
        kwargs={"job_application_id": job_application.pk, "company_pk": other_company.pk},
    )
    transfer_step_3_url = f"{transfer_step_3_base_url}?back_url={quote(transfer_step_2_url)}"
    response = client.get(transfer_step_3_url)
    assertContains(response, PREVIOUS_RESUME_TEXT)

    mocker.patch(
        "itou.www.apply.views.submit_views.uuid.uuid4",
        return_value=uuid.UUID("11111111-1111-1111-1111-111111111111"),
    )
    response = client.post(
        transfer_step_3_url, data={"message": "blah", "resume": pdf_file, "keep_original_resume": "False"}
    )
    new_job_application = JobApplication.objects.filter(to_company=other_company).get()
    assertRedirects(
        response,
        reverse(
            "apply:job_application_external_transfer_step_end",
            kwargs={"job_application_id": new_job_application.pk},
        ),
    )
    assert new_job_application.message == "blah"
    assert new_job_application.job_seeker == job_application.job_seeker
    assert new_job_application.sender == employer
    assert new_job_application.resume_link == (
        f"{settings.AWS_S3_ENDPOINT_URL}tests/{storages['public'].location}"
        f"/resume/11111111-1111-1111-1111-111111111111.pdf"
    )
    assert new_job_application.state == JobApplicationState.NEW


def test_full_process(client):
    create_test_romes_and_appellations(["N1101"], appellations_per_rome=1)
    vannes = create_city_vannes()
    COMPANY_VANNES = "Entreprise Vannes"
    other_company = CompanyFactory(name=COMPANY_VANNES, coords=vannes.coords, post_code="56760", with_membership=True)

    job_application = JobApplicationFactory(
        state=JobApplicationState.REFUSED,
        for_snapshot=True,
        to_company__post_code="56760",
        to_company__coords=vannes.coords,
        to_company__city=vannes.name,
    )
    employer = job_application.to_company.members.get()
    client.force_login(employer)

    # STEP 1
    transfer_step_1_url = reverse(
        "apply:job_application_external_transfer_step_1", kwargs={"job_application_id": job_application.pk}
    )
    response = client.get(transfer_step_1_url, follow=True)
    assertRedirects(response, transfer_step_1_url + "?city=vannes-56")
    assertContains(response, "<h1>Rechercher un emploi inclusif</h1>", html=True)

    transfer_step_2_base_url = reverse(
        "apply:job_application_external_transfer_step_2",
        kwargs={"job_application_id": job_application.pk, "company_pk": other_company.pk},
    )
    transfer_step_2_url = f"{transfer_step_2_base_url}?back_url={quote(transfer_step_1_url)}"
    assertContains(response, transfer_step_2_url)

    # STEP 2
    response = client.get(transfer_step_2_url)
    assertContains(response, "<h2>Sélectionner les métiers recherchés</h2>", html=True)
    assert response.context["form"].initial == {"selected_jobs": [], "spontaneous_application": True}
    # CHeck back_url
    assertContains(response, transfer_step_1_url)

    response = client.post(transfer_step_2_url, data={"spontaneous_application": "on"})

    transfer_step_3_base_url = reverse(
        "apply:job_application_external_transfer_step_3",
        kwargs={"job_application_id": job_application.pk, "company_pk": other_company.pk},
    )
    transfer_step_3_url = f"{transfer_step_3_base_url}?back_url={quote(transfer_step_2_url)}"
    assertRedirects(response, transfer_step_3_url)
    assert client.session[f"job_application-{other_company.pk}"] == {"selected_jobs": []}

    # STEP 3
    response = client.get(transfer_step_3_url)
    assertContains(response, "<h2>Finaliser la candidature</h2>", html=True)
    # CHeck back_url
    assertContains(response, transfer_step_2_url)

    response = client.post(transfer_step_3_url, data={"message": "blah", "keep_original_resume": "True"})
    new_job_application = JobApplication.objects.filter(to_company=other_company).get()
    transfer_step_end_url = reverse(
        "apply:job_application_external_transfer_step_end", kwargs={"job_application_id": new_job_application.pk}
    )
    assertRedirects(response, transfer_step_end_url)
    assert new_job_application.message == "blah"
    assert new_job_application.job_seeker == job_application.job_seeker
    assert new_job_application.sender == employer
    assert new_job_application.state == JobApplicationState.NEW

    transfer_log = job_application.logs.last()
    assert transfer_log.transition == "external_transfer"
    assert transfer_log.user == employer
    assert transfer_log.target_company == other_company
