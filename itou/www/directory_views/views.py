import enum
import itertools

from django.conf import settings
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.db import models
from django.shortcuts import render

from itou.companies.models import Company, CompanyMembership
from itou.prescribers.models import PrescriberMembership
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.auth import check_request
from itou.utils.pagination import pager
from itou.utils.readonly import readonly_view
from itou.www.directory_views.forms import PeopleSearchForm
from itou.www.directory_views.perms import can_access_directory


DIRECTORY_RADIUS_KM = 20


class MembershipKind(enum.StrEnum):
    COMPANY = "company"
    PRESCRIBER_ORG = "prescriber_org"


MEMBERSHIP_TO_KIND = {
    CompanyMembership: MembershipKind.COMPANY,
    PrescriberMembership: MembershipKind.PRESCRIBER_ORG,
}


def directory_membership_qs(membership_kind, origin, organization_kinds=None, user_name=None):
    within = (origin, D(km=DIRECTORY_RADIUS_KM))

    def membership_qs(base_queryset, org_fieldname):
        coords_lookup = {f"{org_fieldname}__coords__dwithin": within}
        return (
            base_queryset.filter(**coords_lookup)
            .exclude(user__directory_profile__is_opted_out=True)
            .annotate(org_directory_distance_km=Distance(f"{org_fieldname}__coords", origin) / 1_000)
            .annotate(kind=models.Value(membership_kind))
            .select_related("user", org_fieldname)
        )

    match membership_kind:
        case MembershipKind.COMPANY:
            base_queryset = CompanyMembership.objects.filter(company__in=Company.objects.active())
            org_fieldname = "company"
        case MembershipKind.PRESCRIBER_ORG:
            base_queryset = PrescriberMembership.objects.all()
            org_fieldname = "organization"
        case _:
            raise ValueError(membership_kind)
    if organization_kinds:
        base_queryset = base_queryset.filter(**{f"{org_fieldname}__kind__in": organization_kinds})
    if user_name:
        base_queryset = base_queryset.filter(
            user__in=User.objects.filter(kind=UserKind.PROFESSIONAL).search_by_full_name(user_name)
        )

    return membership_qs(base_queryset, org_fieldname)


@check_request(can_access_directory)
@readonly_view
def people_results(request, template_name="directory/people_results.html"):
    # Users from ~1,000 organizations have >5K memberships around them. Pulling
    # them all into Python to sort would be simpler, but takes about a second
    # of CPU time on my idle development machine, so it would take several
    # seconds on production.
    # Using a SQL query to identify memberships ids keeps this view cheap
    # enough (<300 ms).

    MEMBERSHIP_SORT_COLUMNS = [
        "user__last_name",
        "user__first_name",
        "user_id",
        "org_directory_distance_km",
        "kind",
        "pk",
    ]

    origin = request.current_organization.coords
    form = PeopleSearchForm(request.GET)
    if form.is_valid():
        filter_args = [
            origin,
            form.cleaned_data["kind"],
            form.cleaned_data["q"],
        ]
        company_membership_qs = directory_membership_qs(MembershipKind.COMPANY, *filter_args).values_list(
            *MEMBERSHIP_SORT_COLUMNS, named=True
        )
        prescriber_membership_qs = directory_membership_qs(MembershipKind.PRESCRIBER_ORG, *filter_args).values_list(
            *MEMBERSHIP_SORT_COLUMNS, named=True
        )
        memberships = company_membership_qs.union(prescriber_membership_qs).order_by(*MEMBERSHIP_SORT_COLUMNS)
    else:
        # Type doesn’t matter, none are returned.
        memberships = CompanyMembership.objects.none()

    memberships_page = pager(memberships, request.GET.get("page"), items_per_page=settings.PAGE_SIZE_SMALL)

    # Hydrate page memberships.
    company_membership_ids = []
    prescriber_org_membership_ids = []
    page_index = {}
    for i, membership in enumerate(memberships_page):
        match membership.kind:
            case MembershipKind.COMPANY:
                company_membership_ids.append(membership.pk)
            case MembershipKind.PRESCRIBER_ORG:
                prescriber_org_membership_ids.append(membership.pk)
            case _:
                raise ValueError(membership.kind)
        page_index[(membership.kind, membership.pk)] = i
    company_memberships = CompanyMembership.objects.filter(
        pk__in=company_membership_ids,
    ).select_related("user", "company")
    prescriber_org_memberships = PrescriberMembership.objects.filter(
        pk__in=prescriber_org_membership_ids
    ).select_related("user", "organization")

    results = list(itertools.chain(company_memberships, prescriber_org_memberships))
    results.sort(key=lambda m: page_index[(MEMBERSHIP_TO_KIND[m._meta.model], m.pk)])

    memberships_page.object_list = results

    context = {
        "form": form,
        "results": memberships_page,
        "matomo_custom_title": "Annuaire pro - Personnes",
    }
    return render(
        request,
        "directory/includes/people_results.html" if request.htmx else template_name,
        context,
    )
