from functools import partial

import pytest
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertTemplateNotUsed, assertTemplateUsed

from itou.users.models import NirModificationRequest
from itou.utils.constants import ITOU_CONTACT_FORM_URL
from itou.utils.urls import get_absolute_url
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)
from tests.utils.testing import parse_response_to_soup


def test_access_for_job_seeker(client):
    job_seeker = JobSeekerFactory()
    client.force_login(job_seeker)
    url = reverse("job_seekers_views:nir_modification_request", kwargs={"public_id": job_seeker.public_id})
    response = client.get(url)
    assert response.status_code == 200
    assertTemplateUsed(response, "job_seekers_views/nir_modification_request.html")


@pytest.mark.parametrize(
    "factory,status_code",
    [
        (None, 302),
        (JobSeekerFactory, 404),  # Trying to access another job seeker's form
        (PrescriberFactory, 404),
        (partial(PrescriberFactory, membership=True, membership__organization__authorized=True), 200),
        (partial(EmployerFactory, membership=True), 200),
        (ItouStaffFactory, 403),
        (partial(LaborInspectorFactory, membership=True), 403),
    ],
)
@pytest.mark.parametrize("method", ["get", "post"])
def test_access(client, factory, status_code, method):
    job_seeker = JobSeekerFactory()
    if factory:
        client.force_login(factory())
    url = reverse("job_seekers_views:nir_modification_request", kwargs={"public_id": job_seeker.public_id})
    response = getattr(client, method)(url)
    assert response.status_code == status_code


@pytest.mark.parametrize("back_url", [None, "/a/random/url/"])
def test_nir_modification_form_is_consistent(client, back_url):
    job_seeker = JobSeekerFactory()
    client.force_login(job_seeker)
    url = reverse("job_seekers_views:nir_modification_request", kwargs={"public_id": job_seeker.public_id})
    response = client.get(url, data={"back_url": back_url} if back_url else {})
    soup = parse_response_to_soup(response)
    form = soup.select_one("#nir-modification-request form")
    assert form["hx-post"] == url
    assert form["hx-swap"] == "outerHTML"
    assert form["hx-target"] == "#nir-modification-request"
    assert "js-prevent-multiple-submit" in form["class"]
    assert form.select_one('input[name="back_url"]')["value"] == back_url or reverse("dashboard:index")


@pytest.mark.parametrize("is_proxy", [False, True])
def test_nir_modification_request_title_blocks_reflects_actor(client, is_proxy):
    job_seeker = JobSeekerFactory()
    actor = PrescriberFactory(membership=True, membership__organization__authorized=True) if is_proxy else job_seeker
    client.force_login(actor)
    url = reverse("job_seekers_views:nir_modification_request", kwargs={"public_id": job_seeker.public_id})
    response = client.get(url)
    assert response.status_code == 200
    expected_name = job_seeker.get_full_name() if is_proxy else ""
    name_fragment = f" de {expected_name}" if expected_name else ""
    soup = parse_response_to_soup(response)
    title = f"Demande de régularisation NIR{name_fragment}"
    assert title == soup.select_one("h1").text.strip()
    title += " - Les emplois de l'inclusion"
    assert title == soup.select_one("title").text.strip()


@pytest.mark.parametrize(
    "data,error_message",
    [
        (
            {"nir": "", "rationale": "Explication"},
            "Ce champ est obligatoire.",  # empty
        ),
        (
            {"rationale": "Explication"},
            "Ce champ est obligatoire.",  # missing
        ),
        (
            {"nir": "194331398700953", "rationale": "Explication"},
            "Ce numéro n'est pas valide.",  # invalid month
        ),
        (
            {"nir": "190031398700953", "rationale": "Explication"},
            "Le nouveau numéro de sécurité sociale est identique au précédent.",
        ),
        (
            {"nir": "19003139870095", "rationale": "Explication"},
            "Le numéro de sécurité sociale est trop court (15 caractères autorisés).",
        ),
        (
            {"nir": "1900313987009533", "rationale": "Explication"},
            "Le numéro de sécurité sociale est trop long (15 caractères autorisés).",
        ),
    ],
)
def test_create_request_invalid_nir(client, data, error_message):
    client.force_login(PrescriberFactory(membership=True, membership__organization__authorized=True))
    job_seeker = JobSeekerFactory(jobseeker_profile__nir="190031398700953")
    url = reverse("job_seekers_views:nir_modification_request", kwargs={"public_id": job_seeker.public_id})
    response = client.post(url, data=data)
    assert response.status_code == 200
    assert NirModificationRequest.objects.count() == 0
    assertTemplateUsed(response, "job_seekers_views/nir_modification_request.html")
    soup = parse_response_to_soup(response)
    form = soup.select_one("#nir-modification-request form")
    error = form.select_one("#id_nir_error")
    assert error.text.strip() == error_message


@pytest.mark.parametrize(
    "data",
    [
        {"nir": "1 11 11 11 111 111 20", "rationale": ""},
        {"nir": "1 11 11 11 111 111 20"},
    ],
)
def test_create_request_without_rationale(client, data):
    client.force_login(PrescriberFactory(membership=True, membership__organization__authorized=True))
    job_seeker = JobSeekerFactory(jobseeker_profile__nir="190031398700953")
    url = reverse("job_seekers_views:nir_modification_request", kwargs={"public_id": job_seeker.public_id})
    response = client.post(url, data=data)
    assert response.status_code == 200
    assert NirModificationRequest.objects.count() == 0
    assertTemplateUsed(response, "job_seekers_views/nir_modification_request.html")
    soup = parse_response_to_soup(response)
    form = soup.select_one("#nir-modification-request form")
    error = form.select_one("#id_rationale_error")
    assert error.text.strip() == "Ce champ est obligatoire."


@pytest.mark.parametrize(
    "rationale,err_message",
    [
        (
            "a" * (NirModificationRequest.MIN_RATIONALE_LENGTH - 1),
            f"Veuillez fournir des détails (au moins {NirModificationRequest.MIN_RATIONALE_LENGTH} caractères).",
        ),
        (
            "a" * (NirModificationRequest.MAX_RATIONALE_LENGTH + 1),
            f"Assurez-vous que cette valeur comporte au plus {NirModificationRequest.MAX_RATIONALE_LENGTH} caractères",
        ),
    ],
)
def test_create_request_with_invalid_rationale(client, rationale, err_message):
    client.force_login(PrescriberFactory(membership=True, membership__organization__authorized=True))
    job_seeker = JobSeekerFactory(jobseeker_profile__nir="190031398700953")
    url = reverse("job_seekers_views:nir_modification_request", kwargs={"public_id": job_seeker.public_id})
    data = {"nir": "1 11 11 11 111 111 20", "rationale": rationale}
    response = client.post(url, data=data)
    assert NirModificationRequest.objects.count() == 0
    assertTemplateUsed(response, "job_seekers_views/nir_modification_request.html")
    assertContains(response, err_message)


def test_create_with_ongoing_request(client, mailoutbox):
    client.force_login(PrescriberFactory(membership=True, membership__organization__authorized=True))
    job_seeker = JobSeekerFactory(jobseeker_profile__nir="190031398700953")

    # Ongoing request
    nir_modification_request = NirModificationRequest.objects.create(
        jobseeker_profile=job_seeker.jobseeker_profile,
        nir="111111111111318",
        requested_by=job_seeker,
    )
    data = {"nir": "111111111111120", "rationale": "Explication"}
    url = reverse("job_seekers_views:nir_modification_request", kwargs={"public_id": job_seeker.public_id})
    response = client.post(url, data=data)
    assertContains(response, "Une demande est déjà en cours de traitement pour ce candidat.")
    assert NirModificationRequest.objects.count() == 1
    assert len(mailoutbox) == 0

    # Closed request, conflict fixed
    nir_modification_request.processed_at = timezone.now()
    nir_modification_request.save()
    data = {"nir": "111111111111120", "rationale": "Explication"}
    response = client.post(url, data=data)
    assert response.status_code == 200
    assertTemplateUsed(response, "job_seekers_views/nir_modification_success.html")
    assert NirModificationRequest.objects.count() == 2
    assert len(mailoutbox) == 1


@pytest.mark.parametrize("back_url", [None, "/a/random/url/"])
def test_create_request_valid(client, mailoutbox, back_url):
    user = PrescriberFactory(membership=True, membership__organization__authorized=True)
    client.force_login(user)
    job_seeker = JobSeekerFactory(jobseeker_profile__nir="190031398700953")
    rationale_message = "Le NIR affiché ne correspond pas à ma situation."
    data = {
        "nir": "1 11 11 11 111 111 20",  # .format-nir does that.
        "rationale": rationale_message,
    }
    if back_url:
        data["back_url"] = back_url
    url = reverse("job_seekers_views:nir_modification_request", kwargs={"public_id": job_seeker.public_id})

    response = client.post(url, data=data)

    assertTemplateNotUsed(response, "job_seekers_views/nir_modification_form.html")
    assertTemplateUsed(response, "job_seekers_views/nir_modification_success.html")
    assertContains(response, "Confirmation d’envoi de la demande de régularisation de NIR")
    assertContains(response, "Votre demande de régularisation du numéro de sécurité sociale a bien été envoyée")
    assertContains(response, ITOU_CONTACT_FORM_URL)
    assertContains(response, "Retour" if back_url else "Tableau de bord")
    assertContains(response, back_url or reverse("dashboard:index"))

    nir_modification_request = NirModificationRequest.objects.get()
    assert nir_modification_request.jobseeker_profile == job_seeker.jobseeker_profile
    assert nir_modification_request.requested_by == user
    assert nir_modification_request.processed_at is None
    assert nir_modification_request.nir == "111111111111120"
    assert nir_modification_request.rationale == rationale_message

    [email] = mailoutbox
    admin_url = get_absolute_url(
        reverse("admin:users_nirmodificationrequest_change", args=(nir_modification_request.pk,))
    )
    assert admin_url in email.body
