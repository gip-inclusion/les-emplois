from collections import defaultdict

from django.contrib.gis.db.models.functions import Distance
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.shortcuts import render

from itou.prescribers.models import PrescriberOrganization
from itou.siaes.models import Siae
from itou.utils.address.departments import DEPARTMENTS_WITH_DISTRICTS
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
    city = None
    distance = None
    kinds = None
    siaes_page = None
    form = SiaeSearchForm(request.GET or None, initial={"distance": SiaeSearchForm.DISTANCE_DEFAULT})

    if form.is_valid():
        city = form.cleaned_data["city"]
        distance = form.cleaned_data["distance"]
        kinds = form.cleaned_data["kinds"]
        departments = request.GET.getlist("departments")

        siaes = (
            Siae.objects.active()
            .within(city.coords, distance)
            .add_shuffled_rank()
            .annotate(_total_active_members=Count("members", filter=Q(members__is_active=True)))
            # Convert km to m (injected in SQL query)
            .annotate(distance=Distance("coords", city.coords) / 1000)
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
        if kinds:
            siaes = siaes.filter(kind__in=kinds)
        if departments:
            siaes = siaes.filter(department__in=departments)

        # Extract departments from results to inject them as filters
        # The DB contains around 4k SIAE (always fast in Python and no need of iterator())
        departments = set()
        departments_districts = defaultdict(set)
        for siae in siaes:
            # Extract the department of SIAE
            if siae.department:
                departments.add(siae.department)
                # Extract the post_code if it's a district to use it as criteria
                if siae.department in DEPARTMENTS_WITH_DISTRICTS:
                    if int(siae.post_code) <= DEPARTMENTS_WITH_DISTRICTS[siae.department]["max"]:
                        departments_districts[siae.department].add(siae.post_code)

        if departments:
            departments = sorted(departments)
            form.add_field_departements(departments)

        if departments_districts:
            for department, districts in departments_districts.items():
                districts = sorted(districts)
                form.add_field_districts(department, districts)

        siaes_page = pager(siaes, request.GET.get("page"), items_per_page=10)

    context = {
        "form": form,
        "city": city,
        "distance": distance,
        "kinds": kinds,
        "siaes_page": siaes_page,
        # Used to display a specific badge
        "ea_eatt_kinds": [Siae.KIND_EA, Siae.KIND_EATT],
    }
    return render(request, template_name, context)


def search_prescribers_home(request, template_name="search/prescribers_search_home.html"):
    """
    The search home page has a different design from the results page.
    """
    form = PrescriberSearchForm()
    context = {"form": form}
    return render(request, template_name, context)


def search_prescribers_results(request, template_name="search/prescribers_search_results.html"):

    form = PrescriberSearchForm(data=request.GET or None)
    prescriber_orgs_page = None

    if form.is_valid():

        city = form.cleaned_data["city"]
        distance_km = form.cleaned_data["distance"]

        prescriber_orgs = (
            PrescriberOrganization.objects.filter(is_authorized=True)
            .within(city.coords, distance_km)
            .annotate(distance=Distance("coords", city.coords))
            .order_by("distance")
        )
        prescriber_orgs_page = pager(prescriber_orgs, request.GET.get("page"), items_per_page=10)

    context = {"form": form, "prescriber_orgs_page": prescriber_orgs_page}
    return render(request, template_name, context)
