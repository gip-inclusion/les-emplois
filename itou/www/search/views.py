from collections import defaultdict

from django.contrib.gis.db.models.functions import Distance
from django.db.models import Prefetch
from django.shortcuts import render

from itou.common_apps.address.departments import DEPARTMENTS_WITH_DISTRICTS
from itou.prescribers.models import PrescriberOrganization
from itou.siaes.enums import SiaeKind
from itou.siaes.models import Siae, SiaeJobDescription
from itou.utils.pagination import pager
from itou.www.search.forms import PrescriberSearchForm, SiaeSearchForm


def search_siaes_results(request, template_name="search/siaes_search_results.html"):
    city = None
    distance = None
    siaes_page = None
    siaes_step_1 = None

    form = SiaeSearchForm(request.GET or None, initial={"distance": SiaeSearchForm.DISTANCE_DEFAULT})

    if form.is_valid():
        # The filtering is made in 3 steps:
        # 1. query with city and distance
        # 2. extract departments and districts filters from first query
        # 3. final query with all the others criteria
        city = form.cleaned_data["city"]
        distance = form.cleaned_data["distance"]

        # Step 1 - Initial query
        siaes_step_1 = Siae.objects.active().within(city.coords, distance)

        # Step 2
        # Extract departments from results to inject them as filters
        # The DB contains around 4k SIAE (always fast in Python and no need of iterator())
        departments = set()
        departments_districts = defaultdict(set)
        for siae in siaes_step_1:
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

        # Step 3 - Final filtering
        kinds = form.cleaned_data["kinds"]
        departments = request.GET.getlist("departments")
        districts = []
        for department_with_district in DEPARTMENTS_WITH_DISTRICTS:
            districts += request.GET.getlist(f"districts_{department_with_district}")

        siaes = (
            siaes_step_1
            # Convert km to m (injected in SQL query)
            .annotate(distance=Distance("coords", city.coords) / 1000)
            .prefetch_related(
                Prefetch(
                    lookup="job_description_through",
                    queryset=SiaeJobDescription.objects.with_annotation_is_popular().filter(
                        siae__in=siaes_step_1, is_active=True
                    ),
                    to_attr="active_job_descriptions",
                )
            )
            # For sorting let's put siaes in only 2 buckets (boolean has_active_members).
            # If we sort naively by `-_total_active_members` we would show
            # siaes with 10 members (where 10 is the max), then siaes
            # with 9 members, then siaes with 8 members etc...
            # This is clearly not what we want. We want to show siaes with members
            # (whatever the number of members is) then siaes without members.
            .with_has_active_members()
            .with_job_app_score()
            # Sort in 4 subgroups in the following order, each subgroup being sorted by job_app_score.
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
            .order_by("-has_active_members", "block_job_applications", "job_app_score")
        )
        if kinds:
            siaes = siaes.filter(kind__in=kinds)

        if departments:
            siaes = siaes.filter(department__in=departments)

        if districts:
            siaes = siaes.filter(post_code__in=districts)

        siaes_page = pager(siaes, request.GET.get("page"), items_per_page=10)

    context = {
        "city": city,
        "distance": distance,
        "ea_eatt_kinds": [SiaeKind.EA, SiaeKind.EATT],
        "form": form,
        "siaes_page": siaes_page,
        "siaes_step_1": siaes_step_1,
        # Used to display a specific badge
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
    city = None
    distance = None
    form = PrescriberSearchForm(data=request.GET or None, initial={"distance": PrescriberSearchForm.DISTANCE_DEFAULT})
    prescriber_orgs_page = None

    if form.is_valid():

        city = form.cleaned_data["city"]
        distance = form.cleaned_data["distance"]

        prescriber_orgs = (
            PrescriberOrganization.objects.filter(is_authorized=True)
            .within(city.coords, distance)
            .annotate(distance=Distance("coords", city.coords))
            .order_by("distance")
        )
        prescriber_orgs_page = pager(prescriber_orgs, request.GET.get("page"), items_per_page=10)

    context = {"city": city, "distance": distance, "form": form, "prescriber_orgs_page": prescriber_orgs_page}
    return render(request, template_name, context)
