import bisect
import itertools

from django.conf import settings
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.db.models import Exists, OuterRef
from django.shortcuts import render

from itou.companies.models import Company, CompanyMembership
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.auth import check_request
from itou.utils.pagination import pager
from itou.utils.readonly import readonly_view
from itou.www.directory_views.perms import can_access_directory


DIRECTORY_RADIUS_KM = 20


@check_request(can_access_directory)
@readonly_view
def people_results(request, template_name="directory/people_results.html"):
    origin = request.current_organization.coords
    within = (origin, D(km=DIRECTORY_RADIUS_KM))
    companies = Company.objects.active().filter(coords__dwithin=within)
    prescriber_orgs = PrescriberOrganization.objects.filter(coords__dwithin=within)
    people = (
        User.objects.filter(kind=UserKind.PROFESSIONAL)
        .exclude(directory_profile__is_opted_out=True)
        .filter(
            Exists(CompanyMembership.objects.filter(user_id=OuterRef("pk"), company__in=companies))
            | Exists(PrescriberMembership.objects.filter(user_id=OuterRef("pk"), organization__in=prescriber_orgs))
        )
    ).order_by("last_name", "first_name", "pk")

    results = pager(people, request.GET.get("page"), items_per_page=settings.PAGE_SIZE_SMALL)

    people = {person.pk: person for person in results}
    company_memberships = (
        CompanyMembership.objects.filter(user__in=people, company__in=companies)
        .select_related("company")
        .annotate(org_directory_distance_km=Distance("company__coords", origin) / 1_000)
    )
    prescriber_memberships = (
        PrescriberMembership.objects.filter(user__in=people, organization__in=prescriber_orgs)
        .select_related("organization")
        .annotate(org_directory_distance_km=Distance("organization__coords", origin) / 1_000)
    )

    def by_directory_distance(membership):
        return membership.org_directory_distance_km

    for membership in itertools.chain(company_memberships, prescriber_memberships):
        person = people[membership.user_id]
        if not hasattr(person, "directory_memberships"):
            person.directory_memberships = []
        bisect.insort_right(
            person.directory_memberships,
            membership,
            key=by_directory_distance,
        )

    context = {
        "results": results,
        "matomo_custom_title": "Annuaire pro - Personnes",
    }
    return render(request, template_name, context)
