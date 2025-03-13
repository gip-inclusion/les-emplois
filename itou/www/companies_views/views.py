import random
from urllib.parse import urljoin

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.core.cache import caches
from django.core.exceptions import BadRequest, PermissionDenied
from django.db.models import Count, Q
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.views.decorators.http import require_POST
from django.views.generic.base import TemplateView

from itou.cities.models import City
from itou.common_apps.address.departments import department_from_postcode
from itou.common_apps.organizations.views import deactivate_org_member, update_org_admin_role
from itou.companies.models import Company, JobDescription, SiaeFinancialAnnex
from itou.jobs.models import Appellation
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.apis.data_inclusion import DataInclusionApiClient, DataInclusionApiException
from itou.utils.apis.exceptions import GeocodingDataError
from itou.utils.auth import LoginNotRequiredMixin, check_user
from itou.utils.pagination import pager
from itou.utils.perms.company import get_current_company_or_404
from itou.utils.session import SessionNamespace
from itou.utils.urls import add_url_params, get_absolute_url, get_safe_url
from itou.www.apply.views.submit_views import ApplyForJobSeekerMixin
from itou.www.companies_views import forms as companies_forms


ITOU_SESSION_EDIT_COMPANY_KEY = "edit_siae_session_key"

DATA_INCLUSION_API_CACHE_PREFIX = "data_inclusion_api_results"


def displayable_thematique(thematique):
    """Remove the sub-themes (anything after the "--"), capitalize and use spaces instead of dashes."""
    return thematique.split("--")[0].upper().replace("-", " ")


def set_dora_utm_query_params(url: str) -> str:
    utm_params = {"mtm_campaign": "LesEmplois", "mtm_kwd": "GeneriqueDecouvrirService"}
    return add_url_params(url, params=utm_params)


def get_dora_url(source, id, original_url=None):
    if source == "dora" and original_url:
        return original_url
    return urljoin(settings.DORA_BASE_URL, f"/services/di--{source}--{id}")


def get_data_inclusion_services(code_insee):
    if not settings.API_DATA_INCLUSION_BASE_URL or not code_insee:
        return []
    cache_key = f"{DATA_INCLUSION_API_CACHE_PREFIX}:{code_insee}:{timezone.localdate()}"
    cache = caches["failsafe"]
    results = cache.get(cache_key)
    if results is None:
        client = DataInclusionApiClient(
            settings.API_DATA_INCLUSION_BASE_URL,
            settings.API_DATA_INCLUSION_TOKEN,
        )
        try:
            raw_services = client.search_services(code_insee)
        except DataInclusionApiException:
            # 15 minutes seems like a reasonable amount of time for DI to get back on track
            cache.set(cache_key, [], 60 * 15)
            return []

        services = []
        for s in raw_services:
            if s["modes_accueil"] != ["en-presentiel"]:
                continue
            s["thematiques_display"] = {displayable_thematique(t) for t in s["thematiques"]}
            s["dora_service_redirect_url"] = reverse(
                "companies_views:dora_service_redirect",
                kwargs={
                    "source": s["source"],
                    "service_id": s["id"],
                },
            )
            services.append(s)

        random.shuffle(services)

        results = []
        department = code_insee[:2]
        if code_insee.startswith("97") or code_insee.startswith("98"):
            department = code_insee[:3]
        if department in ["59", "67"]:
            for svc in services:
                if svc["source"] == "soliguide":
                    results.append(svc)
                    services.remove(svc)
                    break

        while len(results) < 3 and services:
            for service in services:
                if service["thematiques_display"] - set().union(
                    *[prev_service["thematiques_display"] for prev_service in results]
                ):
                    results.append(service)
                    break
            else:
                results.append(services[0])
            services.remove(results[-1])

        random.shuffle(results)

        # 6 hours is reasonable enough to get fresh results while still avoiding
        # hitting the API too much. The API content is updated daily or hourly;
        # we want changes to be propagated at a reasonable time.
        cache.set(cache_key, results, 60 * 60 * 6)
    return results


def report_tally_url(user, company, job_description=None):
    base_url = "https://tally.so/r/m62GYo"
    params = {"companyID": company.pk}
    if user.pk:
        params["UserID"] = user.pk
    if job_description:
        params["jobdescriptionID"] = job_description.pk
    return add_url_params(base_url, params)


### Main company view


@check_user(lambda user: user.is_employer)
def overview(request, template_name="companies/overview.html"):
    context = {
        "company": request.current_organization,
        "can_show_financial_annexes": request.current_organization.convention_can_be_accessed_by(request.user),
    }
    return render(request, template_name, context)


### Job description views


class JobDescriptionCardView(LoginNotRequiredMixin, ApplyForJobSeekerMixin, TemplateView):
    template_name = "companies/job_description_card.html"

    def setup(self, request, job_description_id, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.job_description = get_object_or_404(
            JobDescription.objects.select_related("appellation", "company", "location"), pk=job_description_id
        )

    def get_context_data(self, **kwargs):
        back_url = get_safe_url(self.request, "back_url")
        company = self.job_description.company
        can_update_job_description = (
            self.request.user.is_authenticated
            and self.request.user.is_employer
            and self.request.current_organization.pk == company.pk
        )

        # select_related on company, location useful for _list_siae_actives_jobs_row.html template
        other_active_jobs = (
            JobDescription.objects.select_related("appellation", "company", "location")
            .filter(is_active=True, company=company)
            .exclude(id=self.job_description.pk)
            .order_by("-updated_at", "-created_at")
        )

        if self.job_description.location:
            code_insee = self.job_description.location.code_insee
        elif company.insee_city:
            code_insee = company.insee_city.code_insee
        else:
            code_insee = None

        return super().get_context_data(**kwargs) | {
            "job": self.job_description,
            "siae": company,
            "can_update_job_description": can_update_job_description,
            "other_active_jobs": other_active_jobs,
            "back_url": back_url,
            "matomo_custom_title": "Détails de la fiche de poste",
            "code_insee": code_insee,
            "report_tally_url": report_tally_url(self.request.user, company, self.job_description),
            "job_app_to_transfer": None,
        }


def job_description_list(request, template_name="companies/job_description_list.html"):
    company = get_current_company_or_404(request)
    job_descriptions = (
        JobDescription.objects.filter(company__pk=company.pk)
        .select_related("location", "company")
        .prefetch_related("appellation", "appellation__rome")
        .order_by("-is_active", Coalesce("last_employer_update_at", "updated_at").desc(), "-created_at")
    )
    page = int(request.GET.get("page") or 1)

    form = companies_forms.BlockJobApplicationsForm(instance=company, data=request.POST or None)

    if request.method == "POST":
        # note (fv): waiting for a proper htmx implementation, this will do meanwhile
        job_description_id = request.POST.get("job_description_id")
        match request.POST.get("action"):
            case "delete":
                # delete method via htmx would be nice
                job_description = JobDescription.objects.filter(company_id=company.pk, pk=job_description_id).first()
                if job_description is not None:
                    job_description.delete()
                    messages.success(request, "La fiche de poste a été supprimée.", extra_tags="toast")
                else:
                    messages.warning(request, "La fiche de poste que vous souhaitez supprimer n'existe plus.")
            case "toggle_active":
                is_active = bool(request.POST.get("job_description_is_active", False))
                if job_description := JobDescription.objects.filter(
                    company_id=company.pk, pk=job_description_id
                ).first():
                    job_description.is_active = is_active
                    update_fields = ["is_active", "updated_at"]
                    if is_active:
                        job_description.last_employer_update_at = timezone.now()
                        update_fields += ["last_employer_update_at"]
                    job_description.save(update_fields=update_fields)
                    if is_active:
                        messages.success(
                            request,
                            "Le recrutement est maintenant ouvert.",
                            extra_tags="toast",
                        )
                    else:
                        messages.warning(
                            request,
                            "Le recrutement est maintenant fermé.",
                            extra_tags="toast",
                        )
                else:
                    messages.error(request, "La fiche de poste que vous souhaitiez modifier n'existe plus.")
            case "toggle_spontaneous_applications":
                set_active = company.spontaneous_applications_open_since is None
                company.spontaneous_applications_open_since = timezone.now() if set_active else None
                company.save(update_fields=["spontaneous_applications_open_since", "updated_at"])
                if company.block_job_applications:
                    messages.warning(
                        request,
                        (
                            "La réception de candidatures est temporairement bloquée.||"
                            "Pour recevoir de nouvelles candidatures, veuillez désactiver le blocage"
                        ),
                        extra_tags="toast",
                    )
                else:
                    if set_active:
                        state = "activées"
                        add_message = messages.success
                    else:
                        state = "désactivées"
                        add_message = messages.warning
                    add_message(request, f"Les candidatures spontanées sont maintenant {state}", extra_tags="toast")
            case "block_job_applications":
                company = form.save()
                if company.block_job_applications:
                    messages.warning(
                        request,
                        (
                            "La réception de candidatures est temporairement bloquée.||"
                            "Pour recevoir de nouvelles candidatures, veuillez désactiver le blocage"
                        ),
                        extra_tags="toast",
                    )
                else:
                    messages.success(
                        request,
                        "La structure peut maintenant recevoir de nouvelles candidatures.",
                        extra_tags="toast",
                    )
            case _:
                messages.error(request, "Cette action n'est pas supportée")

        return HttpResponseRedirect(f"{reverse('companies_views:job_description_list')}?page={page}")

    job_pager = pager(job_descriptions, page, items_per_page=20)

    context = {
        "siae": company,
        "form": form,
        "job_pager": job_pager,
        "page": page,
        "can_show_financial_annexes": company.convention_can_be_accessed_by(request.user),
        "back_url": reverse("dashboard:index"),
    }
    return render(request, template_name, context)


@require_POST
@check_user(lambda user: user.is_employer)
def refresh_spontaneous_applications(request):
    company = get_current_company_or_404(request)
    if company.spontaneous_applications_open_since:
        company.spontaneous_applications_open_since = timezone.now()
        company.save(update_fields=["spontaneous_applications_open_since", "updated_at"])
    return render(
        request,
        "companies/includes/buttons/spontaneous_applications_refresh.html",
        {"company": company, "request": request},
    )


@require_POST
@check_user(lambda user: user.is_employer)
def refresh_job_description(request, job_description_id, for_detail=False):
    company = get_current_company_or_404(request)
    job_description = get_object_or_404(company.job_description_through.all(), pk=job_description_id)
    job_description.last_employer_update_at = timezone.now()
    job_description.save(update_fields=["last_employer_update_at", "updated_at"])
    return render(
        request,
        "companies/includes/buttons/job_description_refresh.html",
        {"job_description": job_description, "for_detail": for_detail, "request": request},
    )


JOB_DESCRIPTION_EDIT_SESSION_KIND = "job_description_edit"


@check_user(lambda user: user.is_employer)
def edit_job_description(
    request,
    edit_session_id=None,
    job_description_id=None,
    template_name="companies/edit_job_description.html",
):
    if edit_session_id:
        session_namespace = SessionNamespace(request.session, JOB_DESCRIPTION_EDIT_SESSION_KIND, edit_session_id)
        if not session_namespace.exists():
            raise Http404
        session_data = session_namespace.as_dict()
    else:
        session_namespace = None
        session_data = {}

    if job_description_id:
        job_description = get_object_or_404(
            JobDescription.objects.select_related("appellation", "location"),
            pk=job_description_id,
            company=request.current_organization,
        )
    else:
        job_description = None

    form = companies_forms.EditJobDescriptionForm(
        request.current_organization, instance=job_description, data=request.POST or None, initial=session_data
    )

    if request.method == "POST" and form.is_valid():
        session_data.update(form.cleaned_data)
        if session_namespace is None:
            session_namespace = SessionNamespace.create_uuid_namespace(
                request.session, JOB_DESCRIPTION_EDIT_SESSION_KIND, session_data
            )
        else:
            session_namespace.update(session_data)
        view_kwargs = {"edit_session_id": session_namespace.name}
        if job_description:
            view_kwargs["job_description_id"] = job_description.pk
        return HttpResponseRedirect(reverse("companies_views:edit_job_description_details", kwargs=view_kwargs))

    return render(request, template_name, {"form": form})


@check_user(lambda user: user.is_employer)
def edit_job_description_details(
    request,
    *,
    edit_session_id,
    job_description_id=None,
    template_name="companies/edit_job_description_details.html",
    **kwargs,
):
    session_namespace = SessionNamespace(request.session, JOB_DESCRIPTION_EDIT_SESSION_KIND, edit_session_id)
    if not session_namespace.exists():
        raise Http404
    session_data = session_namespace.as_dict()

    view_kwargs = {"edit_session_id": session_namespace.name}
    if job_description_id:
        job_description = get_object_or_404(
            JobDescription,
            pk=job_description_id,
            company=request.current_organization,
        )
        view_kwargs["job_description_id"] = job_description.pk
    else:
        job_description = None

    rome = get_object_or_404(Appellation.objects.select_related("rome"), pk=session_data.get("appellation")).rome.code

    form = companies_forms.EditJobDescriptionDetailsForm(
        request.current_organization, instance=job_description, data=request.POST or None, initial=session_data
    )
    if request.method == "POST" and form.is_valid():
        session_namespace.update(form.cleaned_data)
        return HttpResponseRedirect(reverse("companies_views:edit_job_description_preview", kwargs=view_kwargs))

    context = {
        "back_url": reverse("companies_views:edit_job_description", kwargs=view_kwargs),
        "form": form,
        "rome": rome,
        "is_opcs": request.current_organization.is_opcs,
    }

    return render(request, template_name, context)


@check_user(lambda user: user.is_employer)
def edit_job_description_preview(
    request,
    *,
    edit_session_id,
    job_description_id=None,
    template_name="companies/edit_job_description_preview.html",
    **kwargs,
):
    session_namespace = SessionNamespace(request.session, JOB_DESCRIPTION_EDIT_SESSION_KIND, edit_session_id)
    if not session_namespace.exists():
        raise Http404
    session_data = session_namespace.as_dict()

    view_kwargs = {"edit_session_id": session_namespace.name}
    if job_description_id:
        job_description = get_object_or_404(
            JobDescription,
            pk=job_description_id,
            company=request.current_organization,
        )
        view_kwargs["job_description_id"] = job_description.pk
    else:
        job_description = JobDescription()

    job_description.__dict__.update(**session_data)

    if location_pk := session_data.get("location"):
        job_description.location = City.objects.get(pk=location_pk)
    else:
        job_description.location = None

    appellation = Appellation.objects.get(pk=session_data.get("appellation"))
    job_description.appellation = appellation
    job_description.company = request.current_organization

    if request.method == "POST":
        if job_description.is_active:
            job_description.last_employer_update_at = timezone.now()
        job_description.save()
        messages.success(request, "Fiche de poste enregistrée", extra_tags="toast")
        session_namespace.delete()
        return HttpResponseRedirect(reverse("companies_views:job_description_list"))

    context = {
        "back_url": reverse("companies_views:edit_job_description_details", kwargs=view_kwargs),
        "siae": request.current_organization,
        "job": job_description,
    }

    return render(request, template_name, context)


### Financial annexes views


def show_financial_annexes(request, template_name="companies/show_financial_annexes.html"):
    """
    Show a summary of the financial annexes of the convention to the siae admin user. Financial annexes are grouped
    by suffix and only the most relevant one (active if any, or most recent if not) is shown for each suffix.
    """
    current_siae = get_current_company_or_404(request)
    if not current_siae.convention_can_be_accessed_by(request.user):
        raise PermissionDenied

    financial_annexes = []
    if current_siae.convention:
        financial_annexes = current_siae.convention.financial_annexes.all()

    # For each group of AFs sharing the same number prefix, show only the most relevant AF
    # (active if any, or most recent if not). We do this to avoid showing too many AFs and confusing the user.
    prefix_to_af = {}
    for af in financial_annexes:
        prefix = af.number_prefix
        if prefix not in prefix_to_af or af.is_active:
            # Always show an active AF when there is one.
            prefix_to_af[prefix] = af
            continue
        old_suffix = prefix_to_af[prefix].number_suffix
        new_suffix = af.number_suffix
        if not prefix_to_af[prefix].is_active and new_suffix > old_suffix:
            # Show the AF with the latest suffix when there is no active one.
            prefix_to_af[prefix] = af
            continue

    financial_annexes = list(prefix_to_af.values())
    financial_annexes.sort(key=lambda af: af.number, reverse=True)

    context = {
        "siae": current_siae,
        "convention": current_siae.convention,
        "financial_annexes": financial_annexes,
        "can_select_af": current_siae.convention_can_be_changed_by(request.user),
        "siae_is_asp": current_siae.source == Company.SOURCE_ASP,
        "siae_is_user_created": current_siae.source == Company.SOURCE_USER_CREATED,
        "back_url": reverse("dashboard:index"),
    }
    return render(request, template_name, context)


def select_financial_annex(request, template_name="companies/select_financial_annex.html"):
    """
    Let siae admin user select a new convention via a financial annex number.
    """
    current_siae = get_current_company_or_404(request)
    if not current_siae.convention_can_be_changed_by(request.user):
        raise PermissionDenied

    # We only allow the user to select an AF under the same SIREN as the current siae.
    financial_annexes = (
        SiaeFinancialAnnex.objects.select_related("convention")
        .filter(convention__kind=current_siae.kind, convention__siret_signature__startswith=current_siae.siren)
        .order_by("-number")
    )

    # Show only one AF for each AF number prefix to significantly reduce the length of the dropdown when there are
    # many AFs in the same SIREN.
    prefix_to_af = {af.number_prefix: af for af in financial_annexes.all()}
    # The form expects a queryset and not a list.
    financial_annexes = financial_annexes.filter(pk__in=[af.pk for af in prefix_to_af.values()])

    select_form = companies_forms.FinancialAnnexSelectForm(
        data=request.POST or None, financial_annexes=financial_annexes
    )

    if request.method == "POST" and select_form.is_valid():
        financial_annex = select_form.cleaned_data["financial_annexes"]
        current_siae.convention = financial_annex.convention
        current_siae.save()
        message = (
            f"Nous avons bien attaché votre structure à l'annexe financière"
            f" {financial_annex.number_prefix_with_spaces}."
        )
        messages.success(request, message)
        return HttpResponseRedirect(reverse("companies_views:show_financial_annexes"))

    context = {
        "select_form": select_form,
        "back_url": reverse("companies_views:show_financial_annexes"),
    }
    return render(request, template_name, context)


### Company CRUD views


class CompanyCardView(LoginNotRequiredMixin, ApplyForJobSeekerMixin, TemplateView):
    template_name = "companies/card.html"

    def setup(self, request, siae_id, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.company = get_object_or_404(Company.objects.with_has_active_members(), pk=siae_id)

    def get_context_data(self, **kwargs):
        back_url = get_safe_url(self.request, "back_url")
        job_descriptions = JobDescription.objects.filter(company=self.company).select_related(
            "appellation", "location"
        )
        active_job_descriptions = []
        if self.company.block_job_applications:
            other_job_descriptions = job_descriptions
        else:
            other_job_descriptions = []
            for job_desc in job_descriptions:
                if job_desc.is_active:
                    active_job_descriptions.append(job_desc)
                else:
                    other_job_descriptions.append(job_desc)

        return super().get_context_data(**kwargs) | {
            "siae": self.company,
            "active_job_descriptions": active_job_descriptions,
            "other_job_descriptions": other_job_descriptions,
            "matomo_custom_title": "Fiche de la structure d'insertion",
            "code_insee": self.company.insee_city.code_insee if self.company.insee_city else None,
            "siae_card_absolute_url": get_absolute_url(
                reverse("companies_views:card", kwargs={"siae_id": self.company.pk})
            ),
            "report_tally_url": report_tally_url(self.request.user, self.company),
            "back_url": back_url,
            "job_app_to_transfer": None,
        }


def create_company(request, template_name="companies/create_siae.html"):
    current_compny = get_current_company_or_404(request)
    if not request.user.can_create_siae_antenna(parent_siae=current_compny):
        raise PermissionDenied

    form = companies_forms.CreateCompanyForm(
        current_company=current_compny,
        current_user=request.user,
        data=request.POST or None,
        initial={"siret": current_compny.siret, "kind": current_compny.kind, "department": current_compny.department},
    )

    if request.method == "POST" and form.is_valid():
        try:
            company = form.save()
            request.session[global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY] = company.pk
            return HttpResponseRedirect(reverse("dashboard:index"))
        except GeocodingDataError:
            messages.error(request, "L'adresse semble erronée. Veuillez la corriger avant de pouvoir « Enregistrer ».")

    context = {"form": form}
    return render(request, template_name, context)


def edit_company_step_contact_infos(request, template_name="companies/edit_siae.html"):
    if ITOU_SESSION_EDIT_COMPANY_KEY not in request.session:
        request.session[ITOU_SESSION_EDIT_COMPANY_KEY] = {}

    company = get_current_company_or_404(request)
    if not request.is_current_organization_admin:
        raise PermissionDenied

    # Force the "brand" initial data to match either brand, or a capitalized version of the base name.
    # This ensures the filed will be filled with a correct value as default.
    company.brand = company.display_name

    form = companies_forms.EditCompanyForm(
        instance=company, data=request.POST or None, initial=request.session[ITOU_SESSION_EDIT_COMPANY_KEY]
    )
    if request.method == "POST" and form.is_valid():
        request.session[ITOU_SESSION_EDIT_COMPANY_KEY].update(form.cleaned_data)
        request.session.modified = True
        return HttpResponseRedirect(reverse("companies_views:edit_company_step_description"))

    context = {
        "form": form,
        "siae": company,
        "reset_url": get_safe_url(request, "back_url", reverse("dashboard:index")),
    }
    return render(request, template_name, context)


def edit_company_step_description(request, template_name="companies/edit_siae_description.html"):
    if ITOU_SESSION_EDIT_COMPANY_KEY not in request.session:
        return HttpResponseRedirect(reverse("companies_views:edit_company_step_contact_infos"))

    company = get_current_company_or_404(request)
    if not request.is_current_organization_admin:
        raise PermissionDenied

    form = companies_forms.EditSiaeDescriptionForm(
        instance=company, data=request.POST or None, initial=request.session[ITOU_SESSION_EDIT_COMPANY_KEY]
    )

    if request.method == "POST" and form.is_valid():
        request.session[ITOU_SESSION_EDIT_COMPANY_KEY].update(form.cleaned_data)
        request.session.modified = True
        return HttpResponseRedirect(reverse("companies_views:edit_company_step_preview"))

    context = {"form": form, "siae": company, "prev_url": reverse("companies_views:edit_company_step_contact_infos")}
    return render(request, template_name, context)


def edit_company_step_preview(request, template_name="companies/edit_siae_preview.html"):
    if ITOU_SESSION_EDIT_COMPANY_KEY not in request.session:
        return HttpResponseRedirect(reverse("companies_views:edit_company_step_contact_infos"))

    company = get_current_company_or_404(request)
    if not request.is_current_organization_admin:
        raise PermissionDenied

    form_data = request.session[ITOU_SESSION_EDIT_COMPANY_KEY]

    # Update the object's data with the recorded changes, for the preview.
    # NOTE(vperron): This may seem "ugly" but it's probably acceptable here since it:
    # - only takes in pre-validated and cleand data (the ModelForms do call full_clean()
    #   on the underlying models)
    # - enables us to perform a single save() in the whole block instead of at least 2 (custom
    #   form) or 3 (existing forms)
    company.__dict__.update(**form_data)

    if request.method == "POST":
        company.department = department_from_postcode(company.post_code)

        try:
            company.geocode_address()
            company.save()
            # Clear the session now, so that we start fresh if we edit again.
            del request.session[ITOU_SESSION_EDIT_COMPANY_KEY]
            request.session.modified = True
            messages.success(request, "Mise à jour effectuée !", extra_tags="toast")
            return HttpResponseRedirect(reverse("dashboard:index"))
        except GeocodingDataError:
            messages.error(
                request,
                format_html(
                    'L\'adresse semble erronée. Veuillez la <a href="{}">corriger</a> avant de pouvoir « Publier ».',
                    reverse("companies_views:edit_company_step_contact_infos"),
                ),
            )

    context = {
        "siae": company,
        "form_data": form_data,
        "prev_url": reverse("companies_views:edit_company_step_description"),
    }
    return render(request, template_name, context)


### Company memberships views


def members(request, template_name="companies/members.html"):
    company = get_current_company_or_404(request)
    if not company.is_active:
        raise PermissionDenied

    active_company_members = company.companymembership_set.active().select_related("user").all().order_by("joined_at")
    active_company_members_stats = active_company_members.aggregate(
        total_count=Count("pk"),
        admin_count=Count("pk", filter=Q(is_admin=True)),
    )
    pending_invitations = company.invitations.pending()

    context = {
        "siae": company,
        "members": active_company_members,
        "members_stats": active_company_members_stats,
        "pending_invitations": pending_invitations,
        "can_show_financial_annexes": company.convention_can_be_accessed_by(request.user),
        "back_url": reverse("dashboard:index"),
    }
    return render(request, template_name, context)


@check_user(lambda user: user.is_employer)
def deactivate_member(request, public_id, template_name="companies/deactivate_member.html"):
    user = get_object_or_404(User, public_id=public_id)
    return deactivate_org_member(
        request,
        user.id,
        success_url=reverse("companies_views:members"),
        template_name=template_name,
    )


@check_user(lambda user: user.is_employer)
def update_admin_role(request, action, public_id, template_name="companies/update_admins.html"):
    if action not in ["add", "remove"]:
        raise BadRequest("Invalid action")
    user = get_object_or_404(User, public_id=public_id)
    return update_org_admin_role(
        request,
        action,
        user.id,
        success_url=reverse("companies_views:members"),
        template_name=template_name,
    )


@login_not_required
def hx_dora_services(request, code_insee, template_name="companies/hx_dora_services.html"):
    context = {
        "data_inclusion_services": get_data_inclusion_services(code_insee),
        "dora_base_url": set_dora_utm_query_params(settings.DORA_BASE_URL),
    }
    return render(request, template_name, context)


@login_not_required
def dora_service_redirect(request, source: str, service_id: str) -> HttpResponseRedirect:
    client = DataInclusionApiClient(
        settings.API_DATA_INCLUSION_BASE_URL,
        settings.API_DATA_INCLUSION_TOKEN,
    )

    try:
        # No caching: we want to have a hit every time.
        service = client.retrieve_service(source=source, id_=service_id)
    except DataInclusionApiException:
        raise Http404()

    url = set_dora_utm_query_params(get_dora_url(source, service_id, service.get("lien_source", None)))
    return HttpResponseRedirect(url)
