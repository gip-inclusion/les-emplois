import enum
import itertools

from django.conf import settings
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.db import models
from django.shortcuts import render

from itou.companies.models import Company, CompanyMembership
from itou.prescribers.models import PrescriberMembership
from itou.utils.auth import check_request
from itou.utils.pagination import pager
from itou.utils.readonly import readonly_view
from itou.www.directory_views.perms import can_access_directory


DIRECTORY_RADIUS_KM = 20


class MembershipType(enum.StrEnum):
    COMPANY = "company"
    PRESCRIBER_ORG = "prescriber_org"


MEMBERSHIP_TO_KIND = {
    CompanyMembership: MembershipType.COMPANY,
    PrescriberMembership: MembershipType.PRESCRIBER_ORG,
}


@check_request(can_access_directory)
@readonly_view
def people_results(request, template_name="directory/people_results.html"):
    origin = request.current_organization.coords
    within = (origin, D(km=DIRECTORY_RADIUS_KM))

    def membership_qs(base_queryset, org_fieldname):
        coords_lookup = {f"{org_fieldname}__coords__dwithin": within}
        return (
            base_queryset.filter(**coords_lookup)
            .exclude(user__directory_profile__is_opted_out=True)
            .annotate(org_directory_distance_km=Distance(f"{org_fieldname}__coords", origin) / 1_000)
            .annotate(
                membership_kind=models.Value(MEMBERSHIP_TO_KIND[base_queryset.model], output_field=models.CharField())
            )
        ).values_list(
            "membership_kind", "pk", "user__last_name", "user__first_name", "user_id", "org_directory_distance_km"
        )

    company_membership_qs = membership_qs(
        CompanyMembership.objects.filter(company__in=Company.objects.active()), "company"
    )
    prescriber_membership_qs = membership_qs(PrescriberMembership.objects.all(), "organization")
    memberships = company_membership_qs.union(prescriber_membership_qs).order_by(
        "user__last_name", "user__first_name", "user_id", "org_directory_distance_km"
    )
    memberships_page = pager(memberships, request.GET.get("page"), items_per_page=settings.PAGE_SIZE_SMALL)

    company_membership_ids = []
    prescriber_org_membership_ids = []
    for membership in memberships_page:
        kind, pk, *_ = membership
        match kind:
            case MembershipType.COMPANY:
                company_membership_ids.append(pk)
            case MembershipType.PRESCRIBER_ORG:
                prescriber_org_membership_ids.append(pk)
            case _:
                raise ValueError(kind)
    company_memberships = CompanyMembership.objects.filter(
        pk__in=company_membership_ids,
    ).select_related("user", "company")
    prescriber_org_memberships = PrescriberMembership.objects.filter(
        pk__in=prescriber_org_membership_ids
    ).select_related("user", "organization")

    def membership_page_index(membership_obj):
        """Reuse sort from the memberships QuerySet."""
        obj_kind = MEMBERSHIP_TO_KIND[membership_obj._meta.model]
        for i, membership in enumerate(memberships_page.object_list):
            kind, pk, *_ = membership
            if kind == obj_kind and pk == membership_obj.pk:
                return i
        raise ValueError(f"{membership_obj} not in list")

    results = list(itertools.chain(company_memberships, prescriber_org_memberships))
    results.sort(key=membership_page_index)

    # TODO: Untested.
    memberships_page.object_list = results

    context = {
        "results": memberships_page,
        "matomo_custom_title": "Annuaire pro - Personnes",
    }
    return render(request, template_name, context)
