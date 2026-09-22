from django.http import Http404
from django.shortcuts import render
from django.urls import reverse

from itou.cities.cache import get_directory_active_city_ids
from itou.directory.services import get_directory_person
from itou.utils.auth import check_request
from itou.utils.readonly import readonly_view
from itou.utils.urls import get_safe_url


def can_access_directory(request):
    organization = getattr(request, "current_organization", None)
    return bool(
        request.user.is_professional
        and organization
        and organization.coords
        and organization.insee_city_id in get_directory_active_city_ids()
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
            fallback_url=reverse("dashboard:index"),
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
