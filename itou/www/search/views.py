from django.contrib.auth.decorators import login_required
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.shortcuts import render

from itou.prescribers.models import PrescriberOrganization
from itou.siaes.models import Siae
from itou.utils.pagination import pager
from itou.www.search.forms import PrescriberSearchForm, SiaeSearchForm


def search_siaes_home(request, template_name="search/siaes_search_home.html"):
    """
    The search home page has a different design from the results page.
    """
    form = SiaeSearchForm()
    context = {"form": form}
    return render(request, template_name, context)


def search_siaes_results(request, template_name="search/siaes_search_results.html"):

    form = SiaeSearchForm(data=request.GET or None)
    siaes_page = None

    if form.is_valid():

        city = form.cleaned_data["city"]
        distance_km = form.cleaned_data["distance"]
        kind = form.cleaned_data["kind"]

        siaes = (
            Siae.objects.active()
            .within(city.coords, distance_km)
            .add_shuffled_rank()
            .annotate(_total_active_members=Count("members", filter=Q(members__is_active=True)))
            # For sorting let's put siaes in only 2 buckets (boolean has_active_members).
            # If we sort naively by `-_total_active_members` we would show
            # siaes with 10 members (where 10 is the max), then siaes
            # with 9 members, then siaes with 8 members etc...
            # This is clearly not what we want. We want to show siaes with members
            # (whatever the number of members is) then siaes without members.
            .annotate(
                has_active_members=Case(
                    When(_total_active_members__gte=1, then=Value(1)), default=Value(0), output_field=IntegerField()
                )
            )
            .prefetch_job_description_through(is_active=True)
            .prefetch_related("members")
            # Sort in 4 subgroups in the following order, each subgroup being shuffled.
            # 1) has_active_members and not block_job_applications
            # These are the siaes which can currently hire, and should be on top.
            # 2) has_active_members and block_job_applications
            # These are the siaes currently blocking job applications, they should
            # be rather high in the list since they are likely to hire again.
            # 3) not has_active_members and not block_job_applications
            # These are the siaes with no member, they should show last.
            # 4) not has_active_members and block_job_applications
            # This group is supposed to be empty. But itou staff may have
            # detached members from their siae so it could still happen.
            .order_by("-has_active_members", "block_job_applications", "shuffled_rank")
        )
        if kind:
            siaes = siaes.filter(kind=kind)
        siaes_page = pager(siaes, request.GET.get("page"), items_per_page=10)

    context = {"form": form, "siaes_page": siaes_page}
    return render(request, template_name, context)


@login_required
def search_prescribers_home(request, template_name="search/prescribers_search_home.html"):
    """
    The search home page has a different design from the results page.
    """
    form = PrescriberSearchForm()
    context = {"form": form}
    return render(request, template_name, context)


@login_required
def search_prescribers_results(request, template_name="search/prescribers_search_results.html"):

    form = PrescriberSearchForm(data=request.GET or None)
    prescriber_orgs_page = None

    if form.is_valid():

        city = form.cleaned_data["city"]
        distance_km = form.cleaned_data["distance"]

        prescriber_orgs = PrescriberOrganization.objects.filter(is_authorized=True).within(city.coords, distance_km)
        prescriber_orgs_page = pager(prescriber_orgs, request.GET.get("page"), items_per_page=10)

    context = {"form": form, "prescriber_orgs_page": prescriber_orgs_page}
    return render(request, template_name, context)
