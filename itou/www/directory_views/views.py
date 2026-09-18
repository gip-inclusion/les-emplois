from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse

from itou.cities.cache import get_directory_active_city_ids
from itou.directory.enums import ContactMethod
from itou.directory.services import get_directory_people, get_directory_person
from itou.utils.auth import check_request
from itou.utils.pagination import pager
from itou.utils.readonly import readonly_view
from itou.utils.urls import get_safe_url
from itou.www.directory_views.forms import PeopleSearchForm


def can_access_directory(request):
    organization = getattr(request, "current_organization", None)
    return bool(
        request.user.is_professional
        and organization
        and organization.coords
        and organization.insee_city_id in get_directory_active_city_ids()
    )


def _normalize_name(value):
    return " ".join(value.replace("-", " ").casefold().split())


def _matches_name(person, query):
    normalized_name = _normalize_name(person.full_name)
    return all(token in normalized_name for token in _normalize_name(query).split())


def _filter_people(people, form):
    query = form.cleaned_data["q"]
    structure_types = set(form.cleaned_data["types"])
    contact_methods = set(form.cleaned_data["contacts"])
    if query:
        people = [person for person in people if _matches_name(person, query)]
    if structure_types:
        people = [
            person
            for person in people
            if structure_types.intersection(organization.kind for organization in person.organizations)
        ]
    if ContactMethod.PHONE in contact_methods:
        people = [person for person in people if person.phone]
    if ContactMethod.EMAIL in contact_methods:
        people = [person for person in people if person.email]
    if ContactMethod.FORM in contact_methods:
        people = [person for person in people if person.has_contact_form]
    return people


@check_request(can_access_directory)
@readonly_view
def people_results(request, template_name="directory/people_results.html"):
    form = PeopleSearchForm(request.GET)
    people = []
    if form.is_valid():
        people = _filter_people(get_directory_people(request.current_organization.coords), form)
    results = pager(people, request.GET.get("page"), items_per_page=settings.PAGE_SIZE_SMALL)
    context = {
        "form": form,
        "results": results,
        "matomo_custom_title": "Annuaire pro - Personnes",
    }
    return render(
        request,
        "directory/includes/people_results.html" if request.htmx else template_name,
        context,
    )


def _get_person(request, key):
    try:
        person = get_directory_person(request.current_organization.coords, key)
    except ValueError as exc:
        raise Http404 from exc
    if not person:
        raise Http404
    return person


def _person_detail_context(request, person):
    return {
        "person": person,
        "back_url": get_safe_url(
            request,
            "back_url",
            fallback_url=reverse("directory:people_results"),
        ),
        "matomo_custom_title": "Annuaire pro - Fiche personne",
    }


@check_request(can_access_directory)
@readonly_view
def person_detail(request, key, template_name="directory/person_detail.html"):
    return render(request, template_name, _person_detail_context(request, _get_person(request, key)))


@check_request(can_access_directory)
@readonly_view
def reveal_contact(request, key, field):
    person = _get_person(request, key)
    if field not in {"email", "phone"}:
        raise Http404
    org_key = request.GET.get("org")
    if org_key:
        organization = next((item for item in person.organizations if item.key == org_key), None)
        if not organization:
            raise Http404
        value = getattr(organization, field)
        label = "Adresse e-mail de la structure" if field == "email" else "Téléphone de la structure"
    else:
        value = getattr(person, field)
        label = "Adresse e-mail" if field == "email" else "Téléphone"
    if not value:
        raise Http404
    return render(
        request,
        "directory/includes/contact_value.html",
        {"label": label, "value": value},
    )
