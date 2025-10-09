import logging
from collections import defaultdict, namedtuple
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.contrib.gis.db.models.functions import Distance
from django.db.models import Case, F, Prefetch, Q, When
from django.shortcuts import render
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import FormView

from itou.common_apps.address.departments import DEPARTMENTS_WITH_DISTRICTS
from itou.companies.enums import CompanyKind, JobSource, JobSourceTag
from itou.companies.models import Company, JobDescription
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.prescribers.enums import PrescriberAuthorizationStatus
from itou.prescribers.models import PrescriberOrganization
from itou.search.models import MAX_SAVED_SEARCHES_COUNT, SavedSearch
from itou.utils.auth import LoginNotRequiredMixin
from itou.utils.htmx import hx_trigger_modal_control
from itou.utils.pagination import pager
from itou.utils.urls import add_url_params
from itou.www.apply.views.submit_views import ApplyForJobSeekerMixin
from itou.www.search_views.forms import (
    JobDescriptionSearchForm,
    NewSavedSearchForm,
    PrescriberSearchForm,
    SiaeSearchForm,
)


# INSEE codes for the french cities that do have districts.
INSEE_CODES_WITH_DISTRICTS = {"13055", "75056", "69123"}


PageAndCounts = namedtuple("PageAndCounts", ("results_page", "siaes_count", "job_descriptions_count"))

logger = logging.getLogger(__name__)


@login_not_required
def employer_search_home(request, template_name="search/siaes_search_home.html"):
    context = {"siae_search_form": SiaeSearchForm()}
    return render(request, template_name, context)


class EmployerSearchBaseView(LoginNotRequiredMixin, ApplyForJobSeekerMixin, FormView):
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

    def get_context_data(self, **kwargs):
        saved_searches = (
            self.request.user.saved_searches.all()
            if self.request.user.is_authenticated
            else SavedSearch.objects.none()
        )
        saved_searches = SavedSearch.add_city_name_attr(saved_searches)

        context = {
            "back_url": reverse("search:employers_home"),
            "clear_filters_url": add_url_params(
                self.request.path, {"city": kwargs["form"].data.get("city")} | self.get_job_seeker_query_string()
            ),
            "filters_query_string": urlencode(self.get_job_seeker_query_string()),
            "job_descriptions_count": 0,
            "siaes_count": 0,
            "results_page": [],
            "display_save_button": False,
            "saved_searches": saved_searches,
            "disable_save_button": len(saved_searches) >= MAX_SAVED_SEARCHES_COUNT,
            # Keep title as “Recherche employeurs solidaires” for matomo stats.
            "matomo_custom_title": "Recherche d'employeurs solidaires",
        }
        context.update(kwargs)
        return super().get_context_data(**context)

    def get_template_names(self):
        return [
            "search/includes/siaes_search_results.html" if self.request.htmx else "search/siaes_search_results.html"
        ]

    def form_valid(self, form):
        city = form.cleaned_data["city"]
        distance = form.cleaned_data["distance"]
        kinds = form.cleaned_data["kinds"]
        # in the case of SIAEs, keep the filter from the URL if present.
        # this enables not losing the count while changing tabs.
        contract_types = form.cleaned_data.get("contract_types", self.request.GET.getlist("contract_types", []))

        siaes = (
            Company.objects.active()
            .within(city.coords, distance)
            .filter(is_searchable=True)
            .annotate(distance=Distance("coords", city.coords) / 1000)
        )
        job_descriptions = (
            JobDescription.objects.active()
            .within(city.coords, distance)
            .select_related("company", "location", "appellation")
            .filter(company__is_searchable=True)
            .exclude(company__block_job_applications=True)
            .annotate(
                distance=Case(
                    When(location__isnull=False, then=Distance("location__coords", city.coords) / 1000),
                    When(location__isnull=True, then=Distance("company__coords", city.coords) / 1000),
                )
            )
        )

        form.add_field_departements(city)

        self.add_form_choices(form, siaes)

        if kinds:
            siaes = siaes.filter(kind__in=kinds)
            job_clauses = Q(company__kind__in=kinds)
            if CompanyKind.EA.value in kinds:
                job_clauses |= Q(source_kind=JobSource.PE_API, source_tags__contains=[JobSourceTag.FT_EA_OFFER.value])
            job_descriptions = job_descriptions.filter(job_clauses)

        if contract_types:
            clauses = Q(contract_type__in=[c for c in contract_types if c != JobSourceTag.FT_PEC_OFFER.value])
            if JobSourceTag.FT_PEC_OFFER.value in contract_types:
                clauses |= Q(source_kind=JobSource.PE_API, source_tags__contains=[JobSourceTag.FT_PEC_OFFER])
            job_descriptions = job_descriptions.filter(clauses)

        departments = self.request.GET.getlist("departments")

        districts = []
        for department_with_district in DEPARTMENTS_WITH_DISTRICTS:
            districts += self.request.GET.getlist(f"districts_{department_with_district}")

        if departments:
            siaes = siaes.filter(department__in=departments)
            job_descriptions = job_descriptions.filter(
                Q(location__isnull=False, location__department__in=departments)
                | Q(location__isnull=True, company__department__in=departments)
            )

        if districts:
            siaes = siaes.filter(post_code__in=districts)

        domains = self.request.GET.getlist("domains")
        if domains:
            query = Q()
            for domain in domains:
                query |= Q(appellation__rome__code__startswith=domain)
            job_descriptions = job_descriptions.filter(query)

        company = self.request.GET.get("company")
        if company:
            try:
                clean_company_pk = int(company)
            except ValueError:
                clean_company_pk = None
            else:
                siaes = siaes.filter(pk=clean_company_pk)

        results_and_counts = self.get_results_page_and_counts(siaes, job_descriptions)

        new_saved_search_form = None
        if self.request.user.is_authenticated:
            new_saved_search_form = NewSavedSearchForm(
                user=self.request.user, initial={"name": city.name, "query_params": self.request.GET.urlencode()}
            )

        context = {
            "form": form,
            "ea_eatt_kinds": [CompanyKind.EA, CompanyKind.EATT],
            "city": city,
            "distance": distance,
            "filters_query_string": urlencode(
                {
                    "city": city.slug,
                    "distance": distance,
                    "kinds": kinds,
                    "contract_types": contract_types,
                    "departments": departments,
                    "domains": domains,
                }
                | self.get_job_seeker_query_string(),
                doseq=True,
            ),
            "results_page": results_and_counts.results_page,
            "siaes_count": results_and_counts.siaes_count,
            "job_descriptions_count": results_and_counts.job_descriptions_count,
            # Display the save button if the search form is valid and user is connected
            "display_save_button": self.request.user.is_authenticated,
            "new_saved_search_form": new_saved_search_form,
        }
        return render(self.request, self.get_template_names(), self.get_context_data(**context))


class EmployerSearchView(EmployerSearchBaseView):
    def add_form_choices(self, form, siaes):
        # Extract departments from results to inject them as filters
        # The DB contains around 4k SIAE (always fast in Python and no need of iterator())
        departments_districts = defaultdict(set)
        company_choices = []
        for siae in siaes:
            company_choices.append((siae.pk, siae.display_name))
            # Extract the post_code if it's a district to use it as criteria
            if (
                siae.department in DEPARTMENTS_WITH_DISTRICTS
                and int(siae.post_code) <= DEPARTMENTS_WITH_DISTRICTS[siae.department]["max"]
            ):
                departments_districts[siae.department].add(siae.post_code)

        city = form.cleaned_data["city"]
        if departments_districts and city.code_insee in INSEE_CODES_WITH_DISTRICTS:
            for department, districts in departments_districts.items():
                districts = sorted(districts)
                form.add_field_districts(department, districts)

        if company_choices:
            form.add_field_company(company_choices)

    def get_results_page_and_counts(self, siaes, job_descriptions):
        siaes = (
            siaes.prefetch_related(
                Prefetch(
                    lookup="job_description_through",
                    queryset=JobDescription.objects.with_annotation_is_unpopular()
                    .filter(company__in=siaes, is_active=True)
                    .select_related("appellation", "location", "company"),
                    to_attr="active_job_descriptions",
                )
            )
            .with_is_hiring()
            .with_has_active_members()
            # Split results into 4 buckets shown in the following order, each bucket being internally sorted
            # by job_app_score.
            # 1) has_active_members and is_hiring
            # These are the siaes which can currently hire, and should be on top.
            # 2) has_active_members and not is_hiring
            # These are the siaes not currently hiring, they should
            # be rather high in the list since they are likely to hire again.
            # 3) not has_active_members and is_hiring
            # These are the siaes with no member, they should show last because noone
            # is there to process any job application.
            # 4) not has_active_members and not is_hiring
            # This group is supposed to be empty. But itou staff may have
            # detached members from their siae so it could still happen.
            .order_by(
                "-has_active_members",
                "-is_hiring",
                "job_app_score",
                "pk",  # ensure a deterministic order for tests and pagination
            )
        )

        page = pager(siaes, self.request.GET.get("page"), items_per_page=settings.PAGE_SIZE_SMALL)
        return PageAndCounts(
            results_page=page,
            siaes_count=page.paginator.count,
            job_descriptions_count=job_descriptions.count(),
        )


class JobDescriptionSearchView(EmployerSearchBaseView):
    form_class = JobDescriptionSearchForm

    # FIXME(vperron): on a un problème ici, c'est que les gens ne peuvent pas sélectionner
    # un arrondissement au moment de la création d'une JobDescription: ils n'ont accès que aux "Cities"
    # qui ne détaillent pas les arrondissements.
    # Ce qui signifie que l'info est perdue dès le départ, à moins que l'on ne change le parcours
    # de création des fiches de poste ou en enrichissant la table "Cities" de tous les arrondissements
    # de Paris, Lyon et Marseille.
    # En attendant on ne pourra pas trier par arrondissement pour ces offres.

    def add_form_choices(self, form, siaes):
        pass

    def get_results_page_and_counts(self, siaes, job_descriptions):
        job_descriptions = job_descriptions.order_by(F("source_kind").asc(nulls_first=True), "-updated_at")

        page = pager(job_descriptions, self.request.GET.get("page"), items_per_page=settings.PAGE_SIZE_SMALL)
        # Prefer a prefetch_related over annotating the entire queryset with_annotation_is_unpopular().
        # That annotation is quite expensive and PostgreSQL runs it on the entire queryset, even
        # though we don’t sort or group by that column. It would be smarter to apply the limit
        # before computing the annotation, but that’s not what PostgreSQL 15 does on 2024-02-21.
        page.object_list = page.object_list.prefetch_related(
            Prefetch(
                "jobapplication_set",
                to_attr="jobapplication_set_pending",
                queryset=JobApplication.objects.filter(state__in=JobApplicationWorkflow.PENDING_STATES),
            )
        )
        for job_description in page.object_list:
            job_description.is_unpopular = (
                len(job_description.jobapplication_set_pending) <= job_description._meta.model.UNPOPULAR_THRESHOLD
            )
        return PageAndCounts(
            results_page=page,
            siaes_count=siaes.count(),
            job_descriptions_count=page.paginator.count,
        )


@login_not_required
def search_prescribers_home(request, template_name="search/prescribers_search_home.html"):
    """
    The search home page has a different design from the results page.
    """
    form = PrescriberSearchForm()
    context = {"form": form}
    return render(request, template_name, context)


@login_not_required
def search_prescribers_results(request, template_name="search/prescribers_search_results.html"):
    city = None
    distance = None
    form = PrescriberSearchForm(data=request.GET or None, initial={"distance": PrescriberSearchForm.DISTANCE_DEFAULT})
    prescriber_orgs = []

    if form.is_valid():
        city = form.cleaned_data["city"]
        distance = form.cleaned_data["distance"]

        prescriber_orgs = (
            PrescriberOrganization.objects.filter(
                authorization_status=PrescriberAuthorizationStatus.VALIDATED,
            )
            .within(city.coords, distance)
            .annotate(distance=Distance("coords", city.coords))
            .order_by("distance")
        )
    prescriber_orgs_page = pager(prescriber_orgs, request.GET.get("page"), items_per_page=settings.PAGE_SIZE_SMALL)

    context = {
        "city": city,
        "distance": distance,
        "form": form,
        "prescriber_orgs_page": prescriber_orgs_page,
        "matomo_custom_title": "Recherche d'organisations prescriptrices",
        "back_url": reverse("search:prescribers_home"),
    }
    return render(
        request,
        "search/includes/prescribers_search_results.html" if request.htmx else template_name,
        context,
    )


@require_POST
def add_saved_search(request):
    form = NewSavedSearchForm(user=request.user, data=request.POST)

    headers = {}
    if form.is_valid():
        form.save()
        form = NewSavedSearchForm(
            user=request.user,
            initial={"name": form.cleaned_data["name"], "query_params": form.cleaned_data["query_params"]},
        )
        headers |= hx_trigger_modal_control("newSavedSearchModal", "hide")
        logger.info("user=%d created a saved search", request.user.pk)

    saved_searches = SavedSearch.add_city_name_attr(request.user.saved_searches.all())

    context = {
        "form": form,
        "saved_searches": saved_searches,
        "display_save_button": True,
        "disable_save_button": len(saved_searches) >= MAX_SAVED_SEARCHES_COUNT,
        "hx_swap_oob": False,
    }

    return TemplateResponse(
        request=request,
        template="search/includes/new_saved_search_modal_content.html",
        context=context,
        headers=headers,
    )


@require_POST
def delete_saved_search(request):
    if (saved_search_id := request.POST.get("saved_search_id")).isdigit():
        del_count, _ = request.user.saved_searches.filter(id=saved_search_id).delete()
        logger.info("user=%d deleted %d saved search", request.user.pk, del_count)

    saved_searches = SavedSearch.add_city_name_attr(request.user.saved_searches.all())
    headers = hx_trigger_modal_control("savedSearchesSettingsModal", "hide") if not saved_searches else {}
    return TemplateResponse(
        request=request,
        template="search/includes/saved_searches_settings_modal_content.html",
        context={
            "saved_searches": saved_searches,
            "display_save_button": True,
            "disable_save_button": len(saved_searches) >= MAX_SAVED_SEARCHES_COUNT,
            "hx_swap_oob": False,
        },
        headers=headers,
    )
