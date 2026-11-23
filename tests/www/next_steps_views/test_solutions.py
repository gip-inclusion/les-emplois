import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from itou.companies.enums import ProSupportReportBarrier as Barrier
from itou.eligibility.enums import AdministrativeCriteriaKind as Kind
from itou.insertion.enums import GenericReferenceItemKind, MobilizationEventKind
from itou.insertion.models import MobilizationEmail, MobilizationEvent, Orientation
from itou.job_applications.enums import SenderKind
from tests.cities.factories import create_city_vannes
from tests.companies.factories import CompanyMembershipFactory
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.insertion.factories import GenericReferenceItemFactory, RemoteReceptionFactory, ServiceFactory
from tests.users.factories import JobSeekerFactory


HTMX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture(autouse=True)
def experiment_for_everyone(settings):
    settings.NEXT_STEPS_FOR_EVERYONE = True


@pytest.fixture
def employer():
    return CompanyMembershipFactory(company__subject_to_iae_rules=True).user


@pytest.fixture
def vannes():
    return create_city_vannes()


def thematic(value):
    return GenericReferenceItemFactory(kind=GenericReferenceItemKind.THEMATIC, value=value, label=value)


def near(city, **kwargs):
    return ServiceFactory(coordinates=city.coords, city=city.name, post_code="56000", **kwargs)


def solutions_url(job_seeker, barrier, **query):
    return reverse(
        "next_steps_views:solutions",
        kwargs={"public_id": job_seeker.public_id, "barrier": barrier.lower()},
        query=query or None,
    )


def service_url(job_seeker, service, **query):
    return reverse(
        "next_steps_views:service", kwargs={"public_id": job_seeker.public_id, "service_id": service.pk}, query=query
    )


def orientation_url(job_seeker, service):
    pk = f"{job_seeker.public_id}.{service.pk}"
    return reverse("next_steps_views:journey", kwargs={"kind": "orientation", "pk": pk})


def walk(client, url, *answers, **headers):
    data, shown, response = {}, [], None
    for index, step_answers in enumerate(answers):
        data |= step_answers
        shown += list(step_answers)
        response = client.post(url, {**data, "step": index, "nav": "next", "shown": shown}, **headers)
    return response


def job_seeker_in(city):
    job_seeker = JobSeekerFactory(city=city.name, department=city.department, post_code="56000")
    IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=job_seeker, criteria_kinds=[Kind.PM])
    return job_seeker


def test_find_a_solution_in_the_drawer(client, employer, vannes):
    job_seeker = job_seeker_in(vannes)
    mobility = near(vannes, thematics=[thematic("mobilite--preparer-un-permis")])
    remote = near(
        vannes, thematics=[thematic("mobilite--acceder-a-un-vehicule")], receptions=[RemoteReceptionFactory()]
    )
    health = near(vannes, thematics=[thematic("sante--acces-aux-soins")])
    # Too far: the search's own radius.
    far = ServiceFactory(coordinates=Point(5.37, 43.29), city="Marseille", thematics=[thematic("mobilite--x")])
    client.force_login(employer)

    response = client.get(reverse("next_steps_views:job_seeker", kwargs={"public_id": job_seeker.public_id}))
    [card] = response.context["barriers"].to_work
    assert card.solutions_url == solutions_url(job_seeker, Barrier.MOBILITY)
    assertContains(response, f'hx-get="{card.solutions_url}"')

    response = client.get(card.solutions_url, **HTMX)
    assertContains(response, "Services autour de Vannes (56)")
    assertContains(response, mobility.name)
    assertContains(response, remote.name)
    assertNotContains(response, health.name)
    assertNotContains(response, far.name)
    # Each service opens in the drawer, and leads back to the solutions.
    assertContains(response, f'hx-get="{service_url(job_seeker, mobility, frein="mobility")}"')
    # The full search, for its other filters.
    assertContains(response, reverse("search:services_results"))
    # Without JavaScript, a page.
    assert client.get(card.solutions_url).status_code == 200

    response = client.get(solutions_url(job_seeker, Barrier.MOBILITY, accueil="a-distance"), **HTMX)
    assertContains(response, remote.name)
    assertNotContains(response, mobility.name)


def test_without_the_job_seekers_city(client, employer):
    job_seeker = JobSeekerFactory(city="", department="")
    client.force_login(employer)
    response = client.get(solutions_url(job_seeker, Barrier.MOBILITY), **HTMX)
    assertContains(response, "Adresse de l’usager non renseignée")
    assertContains(response, "Recherche complète")


def test_only_the_reports_barriers(client, employer):
    client.force_login(employer)
    assert client.get(solutions_url(JobSeekerFactory(), "AUTRE"), **HTMX).status_code == 404


def test_orient_from_the_drawer(client, employer, vannes, mailoutbox):
    company = employer.company_set.first()
    job_seeker = job_seeker_in(vannes)
    service = near(vannes, thematics=[thematic("mobilite--preparer-un-permis")])
    client.force_login(employer)

    response = client.get(service_url(job_seeker, service, frein="mobility"), **HTMX)
    assertContains(response, service.structure.name)
    assertContains(response, "Retour aux solutions")
    assertContains(response, f'hx-get="{solutions_url(job_seeker, Barrier.MOBILITY)}"')
    url = orientation_url(job_seeker, service)
    assertContains(response, f'hx-get="{url}"')

    response = client.get(url, **HTMX)
    assertContains(response, "Les conditions d’accès au service")
    assertContains(response, "Coordonnées transmises au service")
    response = walk(
        client,
        url,
        {"confirms_conditions": "on"},
        {
            "referent_last_name": employer.last_name,
            "referent_first_name": employer.first_name,
            "referent_phone": "0612345678",
            "referent_email": employer.email,
        },
        {"gdpr_consent": "on"},
        **HTMX,
    )
    assertContains(response, "Demande d’orientation envoyée")
    assert response["HX-Trigger"] == "nextStepsChanged"
    orientation = Orientation.objects.get()
    assert orientation.service == service
    assert orientation.beneficiary == job_seeker
    assert orientation.sender == employer
    assert orientation.sender_kind == SenderKind.EMPLOYER
    assert orientation.sender_company == company
    # The service's e-mail, as from the wizard.
    assert service.contact_email in [address for email in mailoutbox for address in email.to]

    # The barrier is now in progress.
    response = client.get(reverse("next_steps_views:job_seeker", kwargs={"public_id": job_seeker.public_id}))
    assert [card.key for card in response.context["barriers"].in_progress] == [Barrier.MOBILITY]


def test_a_service_that_orients_on_its_own_website(client, employer, vannes):
    job_seeker = job_seeker_in(vannes)
    service = near(vannes, lien_mobilisation="https://service.example.org/orienter")
    client.force_login(employer)

    response = client.get(service_url(job_seeker, service), **HTMX)
    assertContains(response, "Orienter sur son site")
    assertContains(response, 'href="https://service.example.org/orienter"')
    assertNotContains(response, "Orienter vers ce service")
    assert client.get(orientation_url(job_seeker, service), **HTMX).status_code == 404


def test_distance_from_the_job_seekers_home(client, employer, vannes):
    job_seeker = job_seeker_in(vannes)
    # About 3 km east of Vannes' centre.
    job_seeker.coords = Point(-2.78, 47.657, srid=4326)
    job_seeker.save(update_fields=["coords"])
    service = near(vannes, thematics=[thematic("mobilite--preparer-un-permis")])
    client.force_login(employer)

    response = client.get(solutions_url(job_seeker, Barrier.MOBILITY), **HTMX)
    [listed] = response.context["services"]
    assert 2.5 < listed.home_distance < 3.5
    assertContains(response, "km du domicile de l’usager")
    response = client.get(service_url(job_seeker, service), **HTMX)
    assertContains(response, "km du domicile de l’usager")


def test_contact_details_on_request(client, employer, vannes, mailoutbox):
    job_seeker = job_seeker_in(vannes)
    service = near(vannes, contact_phone="0612345678", contact_email="accueil@service.fake")
    client.force_login(employer)

    # Folded: neither the phone nor the e-mail in the page, until asked for.
    response = client.get(service_url(job_seeker, service), **HTMX)
    assertContains(response, "Voir les coordonnées")
    assertNotContains(response, "accueil@service.fake")
    assertNotContains(response, "06 12 34 56 78")
    contact_url = reverse(
        "next_steps_views:service_contact", kwargs={"public_id": job_seeker.public_id, "service_id": service.pk}
    )
    assert client.get(contact_url, **HTMX).status_code == 405

    # Asking records it, as on the full service card.
    response = client.post(contact_url, **HTMX)
    assertContains(response, "06 12 34 56 78")
    assertNotContains(response, 'href="tel:')
    assertContains(response, 'data-it-copy-to-clipboard="0612345678"')
    assertContains(response, "Écrire un e-mail à accueil@service.fake")
    event = MobilizationEvent.objects.get()
    assert event.kind == MobilizationEventKind.SERVICE_CONTACT
    assert event.service == service
    assert event.user == employer

    # The message, prefilled, sent by the platform and linked to that event.
    email_url = reverse(
        "next_steps_views:service_email", kwargs={"public_id": job_seeker.public_id, "service_id": service.pk}
    )
    response = client.get(email_url, **HTMX)
    assertContains(response, "Je souhaiterais orienter un usager vers votre service")
    response = client.post(email_url, {"body": "Bonjour, une question."}, **HTMX)
    assertContains(response, "Le message a bien été envoyé à accueil@service.fake.")
    assert MobilizationEmail.objects.get().mobilization_event == event
    [email] = mailoutbox
    assert email.to == ["accueil@service.fake"]
    assert "Bonjour, une question." in email.body
