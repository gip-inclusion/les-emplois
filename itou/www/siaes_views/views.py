from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext as _

from itou.jobs.models import Appellation
from itou.siaes.models import Siae, SiaeFinancialAnnex, SiaeJobDescription
from itou.utils.perms.siae import (
    require_current_siae,
    require_current_siae_is_active,
    require_current_siae_is_active_or_in_grace_period,
    require_siae_admin,
)
from itou.utils.urls import get_safe_url
from itou.www.siaes_views.forms import BlockJobApplicationsForm, CreateSiaeForm, EditSiaeForm, FinancialAnnexSelectForm


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
@require_current_siae_is_active_or_in_grace_period()
def configure_jobs(request, template_name="siaes/configure_jobs.html", current_siae=None):
    """
    Configure an SIAE's jobs.
    """
    if request.method == "POST":

        current_codes = set(current_siae.job_description_through.values_list("appellation__code", flat=True))
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
                current_siae.jobs.add(appellation, through_defaults=through_defaults)

            # Delete.
            if codes_to_delete:
                appellations = Appellation.objects.filter(code__in=codes_to_delete)
                current_siae.jobs.remove(*appellations)

            # Update.
            for job_through in current_siae.job_description_through.filter(appellation__code__in=codes_to_update):
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

    context = {"siae": current_siae}
    return render(request, template_name, context)


@login_required
@require_current_siae()
@require_siae_admin()
def show_financial_annexes(request, template_name="siaes/show_financial_annexes.html", current_siae=None):
    """
    Show the financial annexes of the convention to the siae admin user.
    """
    if current_siae.kind not in Siae.ELIGIBILITY_REQUIRED_KINDS:
        # This interface only makes sense for SIAE, not for GEIQ EA etc.
        raise Http404
    if current_siae.source not in [Siae.SOURCE_ASP, Siae.SOURCE_USER_CREATED]:
        # This interface does not make sense for staff created siaes, which
        # have no convention yet, and will eventually be converted into
        # siaes of ASP source by `import_siae.py` script.
        raise Http404

    # This code will be simplified in a later iteration once we no longer consider
    # user created siaes as always active.
    asp_source_siae_has_valid_af = current_siae.source == Siae.SOURCE_ASP and current_siae.is_active
    user_created_siae_has_valid_af = (
        current_siae.source == Siae.SOURCE_USER_CREATED
        and current_siae.convention
        and current_siae.convention.is_active
    )

    if asp_source_siae_has_valid_af or user_created_siae_has_valid_af:
        messages.success(
            request,
            _(
                "Votre structure est active car associée à au moins une annexe "
                "financière valide listée ci-dessous. Vous n'avez rien à faire."
            ),
        )
    elif current_siae.source == Siae.SOURCE_ASP:
        # Siaes of ASP source cannot be fixed by user.
        messages.error(
            request,
            _(
                f"Votre structure est inactive car n'est associée à aucune annexe "
                f"financière valide. Contactez nous : {settings.ITOU_EMAIL_ASSISTANCE}"
            ),
        )
    elif current_siae.source == Siae.SOURCE_USER_CREATED:
        # User created siaes can be fixed by the user.
        messages.error(
            request,
            _(
                "Votre structure sera prochainement désactivée car n'est "
                "associée à aucune annexe "
                "financière valide. Veuillez procéder à la sélection d'une "
                "annexe financière valide ci-dessous."
            ),
        )

    financial_annexes = []
    if current_siae.convention:
        financial_annexes = current_siae.convention.financial_annexes.all()

    # For each group of AF with the same number prefix, show only the most relevant AF.
    # We do this to avoid showing too many AFs and confusing the user.
    prefix_to_af = {}
    for af in financial_annexes:
        prefix = af.number_prefix
        if prefix not in prefix_to_af or af.is_active:
            # Always show an active AF when there is one.
            prefix_to_af[prefix] = af
            continue
        old_suffix = prefix_to_af[prefix].number_suffix
        new_suffix = af.number_suffix
        if new_suffix > old_suffix:
            # Show the AF with the latest suffix when there is no active one.
            prefix_to_af[prefix] = af
            continue

    financial_annexes = prefix_to_af.values()

    context = {
        "siae": current_siae,
        "convention": current_siae.convention,
        "financial_annexes": financial_annexes,
        "can_select_af": current_siae.source == Siae.SOURCE_USER_CREATED,
    }
    return render(request, template_name, context)


@login_required
@require_current_siae()
@require_siae_admin()
def select_financial_annex(request, template_name="siaes/select_financial_annex.html", current_siae=None):
    """
    """
    if current_siae.kind not in Siae.ELIGIBILITY_REQUIRED_KINDS:
        # This interface only makes sense for SIAE, not for GEIQ EA etc.
        raise Http404
    if current_siae.source != Siae.SOURCE_USER_CREATED:
        # This interface only makes sense for user created siaes.
        raise Http404

    financial_annexes = SiaeFinancialAnnex.objects.prefetch_related("convention").filter(
        convention__kind=current_siae.kind, convention__siret_signature__startswith=current_siae.siren
    )

    select_form = FinancialAnnexSelectForm(data=request.POST or None, financial_annexes=financial_annexes)

    if request.method == "POST" and select_form.is_valid():
        financial_annex = select_form.cleaned_data["financial_annexes"]
        current_siae.convention = financial_annex.convention
        current_siae.save()
        message = _(f"Nous avons bien attaché votre structure à l'annexe financière {financial_annex.number}.")
        messages.success(request, message)
        return HttpResponseRedirect(reverse("siaes_views:show_financial_annexes"))

    context = {"select_form": select_form}
    return render(request, template_name, context)


@login_required
@require_current_siae_is_active()
@require_siae_admin()
def create_siae(request, template_name="siaes/create_siae.html", current_siae=None):
    """
    Create a new SIAE (Antenne in French).
    """
    form = CreateSiaeForm(
        current_siae=current_siae,
        current_user=request.user,
        data=request.POST or None,
        initial={"siret": current_siae.siret, "kind": current_siae.kind, "department": current_siae.department},
    )

    if request.method == "POST" and form.is_valid():
        siae = form.save(request)
        request.session[settings.ITOU_SESSION_CURRENT_SIAE_KEY] = siae.pk
        return HttpResponseRedirect(reverse_lazy("dashboard:index"))

    context = {"form": form}
    return render(request, template_name, context)


@login_required
@require_current_siae_is_active_or_in_grace_period()
def edit_siae(request, template_name="siaes/edit_siae.html", current_siae=None):
    """
    Edit an SIAE.
    """
    form = EditSiaeForm(instance=current_siae, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Mise à jour effectuée !"))
        return HttpResponseRedirect(reverse_lazy("dashboard:index"))

    context = {"form": form, "siae": current_siae}
    return render(request, template_name, context)


@login_required
@require_current_siae_is_active()
def members(request, template_name="siaes/members.html", current_siae=None):
    """
    List members of an SIAE.
    """
    members = current_siae.siaemembership_set.select_related("user").all().order_by("joined_at")
    pending_invitations = current_siae.invitations.filter(accepted=False).all().order_by("sent_at")

    context = {"siae": current_siae, "members": members, "pending_invitations": pending_invitations}
    return render(request, template_name, context)


@login_required
@require_current_siae_is_active_or_in_grace_period()
def block_job_applications(request, template_name="siaes/block_job_applications.html", current_siae=None):
    """
    Settings: block job applications for given SIAE
    """
    form = BlockJobApplicationsForm(instance=current_siae, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Mise à jour du blocage des candidatures effectuée !"))
        return HttpResponseRedirect(reverse_lazy("dashboard:index"))

    context = {"siae": current_siae, "form": form}

    return render(request, template_name, context)
