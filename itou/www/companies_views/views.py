import random
from urllib.parse import urljoin

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import caches
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from itou.cities.models import City
from itou.common_apps.address.departments import department_from_postcode
from itou.common_apps.organizations.views import deactivate_org_member, update_org_admin_role
from itou.companies.models import Company, JobDescription, SiaeFinancialAnnex
from itou.jobs.models import Appellation
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.apis.data_inclusion import DataInclusionApiClient, DataInclusionApiException
from itou.utils.apis.exceptions import GeocodingDataError
from itou.utils.pagination import pager
from itou.utils.perms.company import get_current_company_or_404
from itou.utils.urls import add_url_params, get_absolute_url, get_safe_url
from itou.www.companies_views import forms as companies_forms


# This is a "magic" value for the number of items for paginator objects.
# Set to 10 because we're humans, but can / must be discussed and pulled-up to settings if an agreement is reached.
NB_ITEMS_PER_PAGE = 10

ITOU_SESSION_EDIT_COMPANY_KEY = "edit_siae_session_key"
ITOU_SESSION_JOB_DESCRIPTION_KEY = "edit_job_description_key"

DATA_INCLUSION_API_CACHE_PREFIX = "data_inclusion_api_results"


def dora_url(source, id, original_url=None):
    if source == "dora" and original_url:
        return original_url
    return urljoin(settings.DORA_BASE_URL, f"/services/di--{source}--{id}")


def displayable_thematique(thematique):
    """Remove the sub-themes (anything after the "--"), capitalize and use spaces instead of dashes."""
    return thematique.split("--")[0].upper().replace("-", " ")


def get_data_inclusion_services(code_insee):
    """Returns 3 random DI services, in a 'stable' way: for a given city and day so that an user
    who refreshes the page or shares the URL would not get different services in the same day.
    """
    if not code_insee:
        return []
    cache_key = f"{DATA_INCLUSION_API_CACHE_PREFIX}:{code_insee}:{timezone.localdate()}"
    cache = caches["failsafe"]
    results = cache.get(cache_key)
    if results is None:
        client = DataInclusionApiClient(settings.API_DATA_INCLUSION_BASE_URL, settings.API_DATA_INCLUSION_TOKEN)
        try:
            services = client.services(code_insee)
        except DataInclusionApiException:
            # 15 minutes seems like a reasonable amount of time for DI to get back on track
            cache.set(cache_key, [], 60 * 15)
            return []

        services = [s for s in services if s["modes_accueil"] == ["en-presentiel"]]
        results = random.sample(services, min(len(services), 3))
        results = [
            r
            | {
                "dora_di_url": dora_url(r["source"], r["id"], r.get("lien_source", None)),
                "thematiques_display": {displayable_thematique(t) for t in r["thematiques"]},
            }
            for r in results
        ]
        cache.set(cache_key, results, 60 * 60 * 24)
    return results


def report_tally_url(user, company, job_description=None):
    base_url = "https://tally.so/r/m62GYo"
    params = {"companyID": company.pk}
    if user.pk:
        params["UserID"] = user.pk
    if job_description:
        params["jobdescriptionID"] = job_description.pk
    return add_url_params(base_url, params)


### Job description views


def job_description_card(request, job_description_id, template_name="companies/job_description_card.html"):
    job_description = get_object_or_404(
        JobDescription.objects.select_related("appellation", "company", "location"), pk=job_description_id
    )
    back_url = get_safe_url(request, "back_url")
    company = job_description.company
    can_update_job_description = (
        request.user.is_authenticated and request.user.is_employer and request.current_organization.pk == company.pk
    )

    # select_related on company, location useful for _list_siae_actives_jobs_row.html template
    others_active_jobs = (
        JobDescription.objects.select_related("appellation", "company", "location")
        .filter(is_active=True, company=company)
        .exclude(id=job_description_id)
        .order_by("-updated_at", "-created_at")
    )

    breadcrumbs = {}
    if can_update_job_description:
        breadcrumbs = {
            "Métiers et recrutements": reverse("companies_views:job_description_list"),
        }

    breadcrumbs.update(
        {
            "Détail du poste": reverse(
                "companies_views:job_description_card",
                kwargs={
                    "job_description_id": job_description_id,
                },
            ),
        }
    )

    if job_description.location:
        code_insee = job_description.location.code_insee
    elif company.insee_city:
        code_insee = company.insee_city.code_insee
    else:
        code_insee = None

    context = {
        "job": job_description,
        "siae": company,
        "can_update_job_description": can_update_job_description,
        "others_active_jobs": others_active_jobs,
        "back_url": back_url,
        "breadcrumbs": breadcrumbs,
        "matomo_custom_title": "Détails de la fiche de poste",
        "code_insee": code_insee,
        "report_tally_url": report_tally_url(request.user, company, job_description),
    }
    return render(request, template_name, context)


@login_required
def job_description_list(request, template_name="companies/job_description_list.html"):
    company = get_current_company_or_404(request)
    job_descriptions = (
        JobDescription.objects.filter(company__pk=company.pk)
        .select_related("location", "company")
        .prefetch_related("appellation", "appellation__rome")
        .order_by_most_recent()
    )
    page = int(request.GET.get("page") or 1)

    # Remove possible obsolete session data when coming from breakcrumbs links and back buttons
    if request.session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY):
        del request.session[ITOU_SESSION_JOB_DESCRIPTION_KEY]

    form = companies_forms.BlockJobApplicationsForm(instance=company, data=request.POST or None)

    if request.method == "POST":
        # note (fv): waiting for a proper htmx implementation, this will do meanwhile
        job_description_id = request.POST.get("job_description_id")
        match (request.POST.get("action")):
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
                    job_description.save(update_fields=["is_active"])
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

    job_pager = pager(job_descriptions, page, items_per_page=NB_ITEMS_PER_PAGE)
    breadcrumbs = {
        "Métiers et recrutements": reverse("companies_views:job_description_list"),
    }

    context = {
        "siae": company,
        "form": form,
        "job_pager": job_pager,
        "page": page,
        "breadcrumbs": breadcrumbs,
    }
    return render(request, template_name, context)


def _get_job_description(session_data):
    if pk := session_data.get("pk"):
        job_description = get_object_or_404(
            JobDescription.objects.select_related(
                "appellation",
                "location",
            ),
            pk=pk,
        )
        return job_description
    return None


@login_required
def edit_job_description(request, template_name="companies/edit_job_description.html"):
    company = get_current_company_or_404(request)
    session_data = request.session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY) or {}
    job_description = _get_job_description(session_data)

    form = companies_forms.EditJobDescriptionForm(
        company, instance=job_description, data=request.POST or None, initial=session_data
    )

    if request.method == "POST" and form.is_valid():
        request.session[ITOU_SESSION_JOB_DESCRIPTION_KEY] = {**session_data, **form.cleaned_data}
        return HttpResponseRedirect(reverse("companies_views:edit_job_description_details"))

    breadcrumbs = {
        "Métiers et recrutements": reverse("companies_views:job_description_list"),
    }
    if job_description and job_description.pk:
        kwargs = {"job_description_id": job_description.pk}
        breadcrumbs.update(
            {
                "Détails du poste": reverse("companies_views:job_description_card", kwargs=kwargs),
                "Modifier une fiche de poste": reverse("companies_views:update_job_description", kwargs=kwargs),
            }
        )
    else:
        breadcrumbs["Créer une fiche de poste"] = reverse("companies_views:edit_job_description")

    context = {
        "form": form,
        "breadcrumbs": breadcrumbs,
    }

    return render(request, template_name, context)


@login_required
def edit_job_description_details(request, template_name="companies/edit_job_description_details.html"):
    company = get_current_company_or_404(request)
    session_data = request.session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY)

    if not session_data:
        return HttpResponseRedirect(reverse("companies_views:edit_job_description"))

    job_description = _get_job_description(session_data)

    if job_appellation_code := session_data.get("job_appellation_code"):
        # TODO(xfernandez): Legacy code, remove me in a few days (time for session to expire)
        rome = get_object_or_404(Appellation.objects.select_related("rome"), pk=job_appellation_code).rome.code
    else:
        rome = get_object_or_404(
            Appellation.objects.select_related("rome"), pk=session_data.get("appellation")
        ).rome.code

    form = companies_forms.EditJobDescriptionDetailsForm(
        company, instance=job_description, data=request.POST or None, initial=session_data
    )

    if request.method == "POST" and form.is_valid():
        # Checkboxes don't emit a value when `False`
        session_data["is_resume_mandatory"] = request.POST.get("is_resume_mandatory", False)
        session_data["is_qpv_mandatory"] = request.POST.get("is_qpv_mandatory", False)

        request.session[ITOU_SESSION_JOB_DESCRIPTION_KEY] = {**session_data, **form.cleaned_data}
        return HttpResponseRedirect(reverse("companies_views:edit_job_description_preview"))

    breadcrumbs = {
        "Métiers et recrutements": reverse("companies_views:job_description_list"),
    }

    if job_description and job_description.pk:
        kwargs = {"job_description_id": job_description.pk}
        breadcrumbs.update(
            {
                "Détails du poste": reverse("companies_views:job_description_card", kwargs=kwargs),
                "Modifier une fiche de poste": reverse("companies_views:update_job_description", kwargs=kwargs),
            }
        )
    else:
        breadcrumbs["Créer une fiche de poste"] = reverse("companies_views:edit_job_description")

    context = {
        "form": form,
        "rome": rome,
        "is_opcs": company.is_opcs,
        "breadcrumbs": breadcrumbs,
    }

    return render(request, template_name, context)


@login_required
def edit_job_description_preview(request, template_name="companies/edit_job_description_preview.html"):
    company = get_current_company_or_404(request)
    session_data = request.session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY)

    if not session_data:
        return HttpResponseRedirect(reverse("companies_views:edit_job_description"))

    job_description = _get_job_description(session_data) or JobDescription()

    job_description.__dict__.update(**session_data)

    if location_code := session_data.get("location_code"):
        # TODO(xfernandez): Legacy code, remove me in a few days (time for session to expire)
        job_description.location = City.objects.get(slug=location_code)
    elif location_pk := session_data.get("location"):
        job_description.location = City.objects.get(pk=location_pk)
    else:
        job_description.location = None

    if job_appellation_code := session_data.get("job_appellation_code"):
        # TODO(xfernandez): Legacy code, remove me in a few days (time for session to expire)
        appellation = Appellation.objects.get(pk=job_appellation_code)
    else:
        appellation = Appellation.objects.get(pk=session_data.get("appellation"))
    job_description.appellation = appellation
    job_description.company = company

    if request.method == "POST":
        try:
            job_description.save()
            messages.success(
                request,
                "Fiche de poste enregistrée",
                extra_tags="toast",
            )
        finally:
            request.session.pop(ITOU_SESSION_JOB_DESCRIPTION_KEY)
            return HttpResponseRedirect(reverse("companies_views:job_description_list"))

    breadcrumbs = {
        "Métiers et recrutements": reverse("companies_views:job_description_list"),
    }

    if job_description and job_description.pk:
        kwargs = {"job_description_id": job_description.pk}
        breadcrumbs.update(
            {
                "Détails du poste": reverse("companies_views:job_description_card", kwargs=kwargs),
                "Modifier une fiche de poste": reverse("companies_views:update_job_description", kwargs=kwargs),
            }
        )
    else:
        breadcrumbs["Créer une fiche de poste"] = reverse("companies_views:edit_job_description")

    context = {
        "siae": company,
        "job": job_description,
        "breadcrumbs": breadcrumbs,
    }

    return render(request, template_name, context)


@login_required
def update_job_description(request, job_description_id):
    request.session[ITOU_SESSION_JOB_DESCRIPTION_KEY] = {"pk": job_description_id}
    return HttpResponseRedirect(reverse("companies_views:edit_job_description"))


### Financial annexes views


@login_required
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
    }
    return render(request, template_name, context)


@login_required
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

    context = {"select_form": select_form}
    return render(request, template_name, context)


### Company CRUD views


def card(request, siae_id, template_name="companies/card.html"):
    company = get_object_or_404(Company.objects.with_has_active_members(), pk=siae_id)
    jobs_descriptions = JobDescription.objects.filter(company=company).select_related("appellation", "location")
    active_jobs_descriptions = []
    if company.block_job_applications:
        other_jobs_descriptions = jobs_descriptions
    else:
        other_jobs_descriptions = []
        for job_desc in jobs_descriptions:
            if job_desc.is_active:
                active_jobs_descriptions.append(job_desc)
            else:
                other_jobs_descriptions.append(job_desc)

    context = {
        "siae": company,
        "active_jobs_descriptions": active_jobs_descriptions,
        "other_jobs_descriptions": other_jobs_descriptions,
        "matomo_custom_title": "Fiche de la structure d'insertion",
        "code_insee": company.insee_city.code_insee if company.insee_city else None,
        "siae_card_absolute_url": get_absolute_url(reverse("companies_views:card", kwargs={"siae_id": company.pk})),
        "report_tally_url": report_tally_url(request.user, company),
    }
    return render(request, template_name, context)


@login_required
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


@login_required
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

    context = {"form": form, "siae": company}
    return render(request, template_name, context)


@login_required
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


@login_required
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
            company.set_coords(company.geocoding_address, post_code=company.post_code)
            company.save()
            # Clear the session now, so that we start fresh if we edit again.
            del request.session[ITOU_SESSION_EDIT_COMPANY_KEY]
            request.session.modified = True
            messages.success(request, "Mise à jour effectuée !")
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


@login_required
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
    }
    return render(request, template_name, context)


@login_required
def deactivate_member(request, user_id, template_name="companies/deactivate_member.html"):
    company = get_current_company_or_404(request)
    target_member = User.objects.get(pk=user_id)

    if deactivate_org_member(request=request, target_member=target_member):
        return HttpResponseRedirect(reverse("companies_views:members"))

    context = {
        "structure": company,
        "target_member": target_member,
    }

    return render(request, template_name, context)


@login_required
def update_admin_role(request, action, user_id, template_name="companies/update_admins.html"):
    company = get_current_company_or_404(request)
    target_member = User.objects.get(pk=user_id)

    if update_org_admin_role(request=request, target_member=target_member, action=action):
        return HttpResponseRedirect(reverse("companies_views:members"))

    context = {
        "action": action,
        "structure": company,
        "target_member": target_member,
    }

    return render(request, template_name, context)


def hx_dora_services(request, code_insee, template_name="companies/hx_dora_services.html"):
    context = {
        "data_inclusion_services": get_data_inclusion_services(code_insee),
        "dora_base_url": settings.DORA_BASE_URL,
    }
    return render(request, template_name, context)
