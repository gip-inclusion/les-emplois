from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.utils.translation import gettext as _

from itou.jobs.models import Appellation
from itou.siaes.models import Siae, SiaeJobDescription
from itou.utils.urls import get_safe_url
from itou.www.siaes_views.forms import CreateSiaeForm, EditSiaeForm


def card(request, siae_id, template_name="siaes/card.html"):
    """
    SIAE's card (or "Fiche" in French).

    # COVID-19 "Operation ETTI".
    Public view (previously private, made public during COVID-19).
    """
    queryset = Siae.objects.prefetch_job_description_through(is_active=True)
    siae = get_object_or_404(queryset, pk=siae_id)
    back_url = get_safe_url(request, "back_url")
    context = {"siae": siae, "back_url": back_url}
    return render(request, template_name, context)


def job_description_card(request, job_description_id, template_name="siaes/job_description_card.html"):
    """
    SIAE's job description card (or "Fiche" in French).

    Public view.
    """
    job_description = get_object_or_404(SiaeJobDescription, pk=job_description_id)
    back_url = get_safe_url(request, "back_url")
    context = {"job": job_description, "siae": job_description.siae, "back_url": back_url}
    return render(request, template_name, context)


@login_required
def configure_jobs(request, template_name="siaes/configure_jobs.html"):
    """
    Configure an SIAE's jobs.
    """
    pk = request.session[settings.ITOU_SESSION_CURRENT_SIAE_KEY]
    queryset = Siae.objects.prefetch_job_description_through().member_required(request.user)
    siae = get_object_or_404(queryset, pk=pk)

    if request.method == "POST":

        current_codes = set(siae.job_description_through.values_list("appellation__code", flat=True))
        submitted_codes = set(request.POST.getlist("code"))

        codes_to_create = submitted_codes - current_codes
        # It is assumed that the codes to delete are not submitted (they must
        # be removed from the DOM via JavaScript). Instead, they are deducted.
        codes_to_delete = current_codes - submitted_codes
        codes_to_update = current_codes - codes_to_delete

        if codes_to_create or codes_to_delete or codes_to_update:

            # Create.
            for code in codes_to_create:
                appellation = Appellation.objects.get(code=code)
                through_defaults = {
                    "custom_name": request.POST.get(f"custom-name-{code}", ""),
                    "description": request.POST.get(f"description-{code}", ""),
                    "is_active": bool(request.POST.get(f"is_active-{code}")),
                }
                siae.jobs.add(appellation, through_defaults=through_defaults)

            # Delete.
            if codes_to_delete:
                appellations = Appellation.objects.filter(code__in=codes_to_delete)
                siae.jobs.remove(*appellations)

            # Update.
            for job_through in siae.job_description_through.filter(appellation__code__in=codes_to_update):
                code = job_through.appellation.code
                new_custom_name = request.POST.get(f"custom-name-{code}", "")
                new_description = request.POST.get(f"description-{code}", "")
                new_is_active = bool(request.POST.get(f"is_active-{code}"))
                if (
                    job_through.custom_name != new_custom_name
                    or job_through.description != new_description
                    or job_through.is_active != new_is_active
                ):
                    job_through.custom_name = new_custom_name
                    job_through.description = new_description
                    job_through.is_active = new_is_active
                    job_through.save()

            messages.success(request, _("Mise à jour effectuée !"))
            return HttpResponseRedirect(reverse_lazy("dashboard:index"))

    context = {"siae": siae}
    return render(request, template_name, context)


@login_required
def create_siae(request, template_name="siaes/create_siae.html"):
    """
    Create a new SIAE (Agence / Etablissement in French).
    """
    current_siae_pk = request.session.get(settings.ITOU_SESSION_CURRENT_SIAE_KEY)
    current_siae = request.user.siae_set.get(pk=current_siae_pk)
    form = CreateSiaeForm(current_siae=current_siae, data=request.POST or None, initial={"siret": current_siae.siret})

    if request.method == "POST" and form.is_valid():
        siae = form.save(request)
        request.session[settings.ITOU_SESSION_CURRENT_SIAE_KEY] = siae.pk
        messages.success(request, _(f"Vous travaillez sur {siae.display_name}"))
        return HttpResponseRedirect(reverse_lazy("dashboard:index"))

    context = {"form": form}
    return render(request, template_name, context)


@login_required
def edit_siae(request, template_name="siaes/edit_siae.html"):
    """
    Edit an SIAE.
    """
    pk = request.session[settings.ITOU_SESSION_CURRENT_SIAE_KEY]
    queryset = Siae.objects.member_required(request.user)
    siae = get_object_or_404(queryset, pk=pk)

    form = EditSiaeForm(instance=siae, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Mise à jour effectuée !"))
        return HttpResponseRedirect(reverse_lazy("dashboard:index"))

    context = {"form": form, "siae": siae}
    return render(request, template_name, context)
