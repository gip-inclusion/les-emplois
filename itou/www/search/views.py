from collections import defaultdict

from django.contrib.gis.db.models.functions import Distance
from django.db.models import Case, F, Prefetch, Q, When
from django.shortcuts import render
from django.views.generic import FormView

from itou.common_apps.address.departments import DEPARTMENTS_WITH_DISTRICTS
from itou.prescribers.models import PrescriberOrganization
from itou.siaes.enums import SiaeKind
from itou.siaes.models import Siae, SiaeJobDescription
from itou.utils.pagination import pager
from itou.www.search.forms import PrescriberSearchForm, SiaeSearchForm


class EmployerSearchBaseView(FormView):

    template_name = "search/siaes_search_results.html"
    form_class = SiaeSearchForm
    initial = {"distance": SiaeSearchForm.DISTANCE_DEFAULT}

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["data"] = self.request.GET or None
        return kwargs

    def get(self, request, *args, **kwargs):
        # rewire the GET onto the POST since in this particular view, the form data is passed by GET
        # to be able to share the search results URL.
        return self.post(request, *args, **kwargs)

    def form_valid(self, form):
        city = form.cleaned_data["city"]
        distance = form.cleaned_data["distance"]
        kinds = form.cleaned_data["kinds"]
        context = {
            "form": form,
            "city": city,
            "distance": distance,
            "kinds_query": "&".join(f"kinds={kind}" for kind in kinds),
            "ea_eatt_kinds": [SiaeKind.EA, SiaeKind.EATT],
        }

        siaes = (
            Siae.objects.active()
            .within(city.coords, distance)
            .annotate(distance=Distance("coords", city.coords) / 1000)
        )
        job_descriptions = (
            SiaeJobDescription.objects.active()
            .within(city.coords, distance)
            .select_related("location")
            .exclude(siae__block_job_applications=True)
            .annotate(
                distance=Case(
                    When(location__isnull=False, then=Distance("location__coords", city.coords) / 1000),
                    When(location__isnull=True, then=Distance("siae__coords", city.coords) / 1000),
                )
            )
        )
        if kinds:
            siaes = siaes.filter(kind__in=kinds)
            job_descriptions = job_descriptions.filter(siae__kind__in=kinds)

        departments = self.request.GET.getlist("departments")

        districts = []
        for department_with_district in DEPARTMENTS_WITH_DISTRICTS:
            districts += self.request.GET.getlist(f"districts_{department_with_district}")

        if departments:
            siaes = siaes.filter(department__in=departments)
            job_descriptions = job_descriptions.filter(
                Q(location__isnull=False, location__department__in=departments)
                | Q(location__isnull=True, siae__department__in=departments)
            )

        if districts:
            siaes = siaes.filter(post_code__in=districts)

        self.add_form_choices(form, siaes, job_descriptions)

        context.update(
            {
                "results_page": self.get_results_page(siaes, job_descriptions),
                "siaes_count": siaes.count(),
                "job_descriptions_count": job_descriptions.count(),
            }
        )

        return render(self.request, self.template_name, context)

    def form_invalid(self, form):
        context = {
            "form": form,
        }
        return render(self.request, self.template_name, context)


class EmployerSearchView(EmployerSearchBaseView):
    def add_form_choices(self, form, siaes, _job_descriptions):
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

    def get_results_page(self, siaes, _job_descriptions):
        siaes = (
            siaes.prefetch_related(
                Prefetch(
                    lookup="job_description_through",
                    queryset=SiaeJobDescription.objects.with_annotation_is_popular().filter(
                        siae__in=siaes, is_active=True
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
            .with_has_active_members().with_job_app_score()
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

        return pager(siaes, self.request.GET.get("page"), items_per_page=10)


class JobDescriptionSearchView(EmployerSearchBaseView):
    def add_form_choices(self, form, _siaes, job_descriptions):
        departments = set()
        for job_description in job_descriptions:
            department = None
            if job_description.location:
                department = job_description.location.department
                # FIXME(vperron): on a un problème ici, c'est que les gens ne peuvent pas sélectionner
                # un arrondissement au moment de la création d'une JobDescription: ils n'ont accès que aux "Cities"
                # qui ne détaillent pas les arrondissements.
                # Ce qui signifie que l'info est perdue dès le départ, à moins que l'on ne change le parcours
                # de création des fiches de poste ou en enrichissant la table "Cities" de tous les arrondissements
                # de Paris, Lyon et Marseille.
                # En attendant on ne pourra pas trier par arrondissement pour ces offres.
            elif job_description.siae.department:
                department = job_description.siae.department
            departments.add(department)

        if departments:
            departments = sorted(departments)
            form.add_field_departements(departments)

    def get_results_page(self, _siaes, job_descriptions):
        job_descriptions = job_descriptions.with_annotation_is_popular().order_by(
            F("updated_at").asc(nulls_last=True), "-created_at"
        )

        return pager(job_descriptions, self.request.GET.get("page"), items_per_page=10)


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
