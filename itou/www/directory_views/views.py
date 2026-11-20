import enum
import itertools

from django.conf import settings
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
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
            .select_related("user", org_fieldname)
            .annotate(org_directory_distance_km=Distance(f"{org_fieldname}__coords", origin) / 1_000)
        )

    company_membership_qs = membership_qs(
        CompanyMembership.objects.filter(company__in=Company.objects.active()), "company"
    )
    prescriber_membership_qs = membership_qs(PrescriberMembership.objects.all(), "organization")
    memberships = list(itertools.chain(company_membership_qs, prescriber_membership_qs))
    memberships.sort(
        key=lambda membership: (
            membership.user.last_name,
            membership.user.first_name,
            membership.user.pk,
            membership.org_directory_distance_km,
        )
    )
    memberships_page = pager(memberships, request.GET.get("page"), items_per_page=settings.PAGE_SIZE_SMALL)
    context = {
        "results": memberships_page,
        "matomo_custom_title": "Annuaire pro - Personnes",
    }
    return render(request, template_name, context)
