from django.conf import settings
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.shortcuts import render

from itou.companies.models import Company, CompanyMembership
from itou.prescribers.models import PrescriberMembership
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.auth import check_request
from itou.utils.pagination import pager
from itou.utils.readonly import readonly_view
from itou.www.directory_views.perms import can_access_directory


DIRECTORY_RADIUS_KM = 20


def _nearby_memberships(queryset, organization_field, users, origin):
    coords_field = f"{organization_field}__coords"
    return (
        queryset.filter(
            user__in=users,
            **{f"{coords_field}__dwithin": (origin, D(km=DIRECTORY_RADIUS_KM))},
        )
        .select_related("user", organization_field)
        .annotate(org_directory_distance=Distance(coords_field, origin) / 1000)
    )


def get_directory_people(origin, *, public_id=None):
    directory = {}
    users = User.objects.filter(kind=UserKind.PROFESSIONAL).exclude(directory_profile__is_opted_out=True)
    if public_id:
        users = users.filter(public_id=public_id)

    for queryset, organization_field in (
        (CompanyMembership.objects.filter(company__in=Company.objects.active()), "company"),
        (PrescriberMembership.objects.all(), "organization"),
    ):
        for membership in _nearby_memberships(queryset, organization_field, users, origin):
            try:
                user = directory[membership.user.pk]
            except KeyError:
                user = membership.user
                user.directory_organizations = []
                directory[membership.user.pk] = user
            org = getattr(membership, organization_field)
            org.directory_distance_km = membership.org_directory_distance
            user.directory_organizations.append(org)
    for person in directory.values():
        person.directory_organizations.sort(
            key=lambda org: (
                org.directory_distance_km,
                org._meta.model_name,
                org.pk,
            )
        )

    return sorted(
        directory.values(),
        key=lambda person: (
            person.last_name,
            person.first_name,
            person.email,
        ),
    )


@check_request(can_access_directory)
@readonly_view
def people_results(request, template_name="directory/people_results.html"):
    people = get_directory_people(request.current_organization.coords)
    results = pager(people, request.GET.get("page"), items_per_page=settings.PAGE_SIZE_SMALL)
    context = {
        "results": results,
        "matomo_custom_title": "Annuaire pro - Personnes",
    }
    return render(request, template_name, context)
