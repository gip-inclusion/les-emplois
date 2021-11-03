from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from itou.common_apps.organizations.views import deactivate_org_member, update_org_admin_role
from itou.jobs.models import Appellation
from itou.siaes.models import Siae, SiaeFinancialAnnex, SiaeJobDescription
from itou.users.models import User
from itou.utils.perms.siae import get_current_siae_or_404
from itou.utils.urls import get_safe_url
from itou.www.siaes_views.forms import (
    BlockJobApplicationsForm,
    CreateSiaeForm,
    EditSiaeForm,
    FinancialAnnexSelectForm,
    ValidateSiaeJobDescriptionForm,
)


def card(request, siae_id, template_name="siaes/card.html"):
    """
    SIAE's card (or "Fiche" in French).

    # COVID-19 "Operation ETTI".
    Public view (previously private, made public during COVID-19).
    """
    queryset = Siae.objects.prefetch_job_description_through(is_active=True).with_job_app_score()
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
    siae = job_description.siae
    # TODO: why request is duplicated ?!
    others_active_jobs = (
        SiaeJobDescription.objects.select_related("appellation")
        .filter(is_active=True, siae=siae)
        .exclude(id=job_description_id)
    )
    context = {
        "job": job_description,
        "siae": siae,
        "others_active_jobs": others_active_jobs,
        "back_url": back_url,
    }
    return render(request, template_name, context)


@login_required
def configure_jobs(request, template_name="siaes/configure_jobs.html"):
    """
    Configure an SIAE's jobs.

    Time was limited during the prototyping phase and this view is based on
    JavaScript to generate a dynamic form. No proper Django form is used.
    """
    siae = get_current_siae_or_404(request)
    job_descriptions = siae.job_description_through.select_related("appellation__rome").all()
    errors = {}

    if request.method == "POST":

        submitted_codes = set(request.POST.getlist("code"))

        # Validate submitted data: this is not the standard way to do things
        # and errors will not be shown at the field level.
        for code in submitted_codes:
            data = {
                # Omit `SiaeJobDescription.appellation` since the field is
                # hidden and `Appellation.objects.get()` will fail anyway.
                "custom_name": request.POST.get(f"custom-name-{code}", ""),
                "description": request.POST.get(f"description-{code}", ""),
                "is_active": bool(request.POST.get(f"is_active-{code}")),
            }
            # We use a single ModelForm instance to validate each submitted group of data.
            form = ValidateSiaeJobDescriptionForm(data=data)
            if not form.is_valid():
                for key, value in form.errors.items():
                    verbose_name = form.fields[key].label
                    error = value[0]
                    # The key of the dict is used in tests.
                    errors[code] = f"{verbose_name} : {error}"

        if not errors:

            current_codes = set(siae.job_description_through.values_list("appellation__code", flat=True))
            codes_to_create = submitted_codes - current_codes
            # It is assumed that the codes to delete are not submitted (they must
            # be removed from the DOM via JavaScript). Instead, they are deducted.
            codes_to_delete = current_codes - submitted_codes
            codes_to_update = current_codes - codes_to_delete
            if codes_to_create or codes_to_delete or codes_to_update:
                with transaction.atomic():
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

                messages.success(request, "Mise à jour effectuée !")
                return HttpResponseRedirect(reverse("dashboard:index"))

    context = {"errors": errors, "job_descriptions": job_descriptions, "siae": siae}
    return render(request, template_name, context)


@login_required
def show_financial_annexes(request, template_name="siaes/show_financial_annexes.html"):
    """
    Show a summary of the financial annexes of the convention to the siae admin user. Financial annexes are grouped
    by suffix and only the most relevant one (active if any, or most recent if not) is shown for each suffix.
    """
    current_siae = get_current_siae_or_404(request)
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
        "current_siae_is_asp": current_siae.source == Siae.SOURCE_ASP,
        "current_siae_is_user_created": current_siae.source == Siae.SOURCE_USER_CREATED,
    }
    return render(request, template_name, context)


@login_required
def select_financial_annex(request, template_name="siaes/select_financial_annex.html"):
    """
    Let siae admin user select a new convention via a financial annex number.
    """
    current_siae = get_current_siae_or_404(request)
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

    select_form = FinancialAnnexSelectForm(data=request.POST or None, financial_annexes=financial_annexes)

    if request.method == "POST" and select_form.is_valid():
        financial_annex = select_form.cleaned_data["financial_annexes"]
        current_siae.convention = financial_annex.convention
        current_siae.save()
        message = (
            f"Nous avons bien attaché votre structure à l'annexe financière"
            f" {financial_annex.number_prefix_with_spaces}."
        )
        messages.success(request, message)
        return HttpResponseRedirect(reverse("siaes_views:show_financial_annexes"))

    context = {"select_form": select_form}
    return render(request, template_name, context)


@login_required
def create_siae(request, template_name="siaes/create_siae.html"):
    """
    Create a new SIAE (Antenne in French).
    """
    current_siae = get_current_siae_or_404(request)
    if not current_siae.is_active or not current_siae.has_admin(request.user):
        raise PermissionDenied
    form = CreateSiaeForm(
        current_siae=current_siae,
        current_user=request.user,
        data=request.POST or None,
        initial={"siret": current_siae.siret, "kind": current_siae.kind, "department": current_siae.department},
    )

    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            # The form creates multiple objects
            siae = form.save(request)

        request.session[settings.ITOU_SESSION_CURRENT_SIAE_KEY] = siae.pk
        return HttpResponseRedirect(reverse("dashboard:index"))

    context = {"form": form}
    return render(request, template_name, context)


@login_required
def edit_siae(request, template_name="siaes/edit_siae.html"):
    """
    Edit an SIAE.
    """
    siae = get_current_siae_or_404(request)
    if not siae.has_admin(request.user):
        raise PermissionDenied

    form = EditSiaeForm(instance=siae, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Mise à jour effectuée !")
        return HttpResponseRedirect(reverse("dashboard:index"))

    context = {"form": form, "siae": siae}
    return render(request, template_name, context)


@login_required
def members(request, template_name="siaes/members.html"):
    """
    List members of an SIAE.
    """
    siae = get_current_siae_or_404(request)
    if not siae.is_active:
        raise PermissionDenied

    members = siae.siaemembership_set.active().select_related("user").all().order_by("joined_at")
    pending_invitations = siae.invitations.pending()

    context = {
        "siae": siae,
        "members": members,
        "pending_invitations": pending_invitations,
    }
    return render(request, template_name, context)


@login_required
def deactivate_member(request, user_id, template_name="siaes/deactivate_member.html"):
    siae = get_current_siae_or_404(request)
    target_member = User.objects.get(pk=user_id)

    if deactivate_org_member(request=request, target_member=target_member, organization=siae):
        return HttpResponseRedirect(reverse("siaes_views:members"))

    context = {
        "structure": siae,
        "target_member": target_member,
    }

    return render(request, template_name, context)


@login_required
def update_admin_role(request, action, user_id, template_name="siaes/update_admins.html"):
    siae = get_current_siae_or_404(request)
    target_member = User.objects.get(pk=user_id)

    if update_org_admin_role(request=request, organization=siae, target_member=target_member, action=action):
        return HttpResponseRedirect(reverse("siaes_views:members"))

    context = {
        "action": action,
        "structure": siae,
        "target_member": target_member,
    }

    return render(request, template_name, context)


@login_required
def block_job_applications(request, template_name="siaes/block_job_applications.html"):
    """
    Settings: block job applications for given SIAE
    """
    siae = get_current_siae_or_404(request)

    form = BlockJobApplicationsForm(instance=siae, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Mise à jour du blocage des candidatures effectuée !")
        return HttpResponseRedirect(reverse("dashboard:index"))

    context = {"siae": siae, "form": form}

    return render(request, template_name, context)
