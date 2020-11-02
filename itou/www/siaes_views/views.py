from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.utils.translation import gettext as _

from itou.jobs.models import Appellation
from itou.siaes.models import Siae, SiaeJobDescription
from itou.users.models import User
from itou.utils.perms.siae import get_current_siae_or_404
from itou.utils.sessions import kill_sessions_for_user
from itou.utils.urls import get_safe_url
from itou.www.siaes_views.forms import BlockJobApplicationsForm, CreateSiaeForm, EditSiaeForm


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
    siae = get_current_siae_or_404(request)

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
    Create a new SIAE (Antenne in French).
    """
    current_siae = get_current_siae_or_404(request)
    if not current_siae.is_active:
        raise PermissionDenied
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
def edit_siae(request, template_name="siaes/edit_siae.html"):
    """
    Edit an SIAE.
   """
    siae = get_current_siae_or_404(request)

    form = EditSiaeForm(instance=siae, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Mise à jour effectuée !"))
        return HttpResponseRedirect(reverse_lazy("dashboard:index"))

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

    members = siae.siaemembership_set.filter(is_active=True).select_related("user").all().order_by("joined_at")
    pending_invitations = siae.invitations.filter(accepted=False).all().order_by("sent_at")

    # TODO Optimize: in one query (via SIAE)?
    deactivated_members = (
        siae.siaemembership_set.filter(is_active=False).select_related("user").all().order_by("updated_at")
    )

    context = {
        "siae": siae,
        "members": members,
        "pending_invitations": pending_invitations,
        "deactivated_members": deactivated_members,
    }
    return render(request, template_name, context)


@login_required
def deactivate_member(request, user_id, template_name="siaes/deactivate_member.html"):
    siae = get_current_siae_or_404(request)
    user = request.user
    target_member = User.objects.get(pk=user_id)

    if target_member not in siae.active_members:
        raise PermissionDenied

    membership = target_member.siaemembership_set.get(siae=siae)

    if request.method == "POST":
        if user != target_member and user in siae.active_admin_members:
            if membership.is_active:
                membership.toggle_user_membership(user)
                membership.save()
                messages.success(
                    request,
                    _("%(name)s a été retiré(e) des membres actifs de cette structure.")
                    % {"name": target_member.get_full_name()},
                )
                siae.new_member_deactivation_email(membership.user).send()
                kill_sessions_for_user(membership.user.pk)
        else:
            raise PermissionDenied
        return HttpResponseRedirect(reverse_lazy("siaes_views:members"))

    context = {
        "siae": siae,
        "target_member": target_member,
    }

    return render(request, template_name, context)


@login_required
def update_admin_role(request, action, user_id, template_name="siaes/update_admins.html"):
    if action not in ["add", "remove"]:
        raise SuspiciousOperation

    siae = get_current_siae_or_404(request)
    user = request.user
    target_member = User.objects.get(pk=user_id)

    if target_member not in siae.active_members:
        raise PermissionDenied

    membership = target_member.siaemembership_set.get(siae=siae)

    if request.method == "POST":
        if user != target_member and user in siae.active_admin_members and membership.is_active:
            if action == "add":
                membership.set_admin_role(True, user)
                messages.success(
                    request,
                    _("%(name)s a été ajouté(e) aux administrateurs de cette structure.")
                    % {"name": target_member.get_full_name()},
                )
                siae.add_admin_email(target_member).send()
            if action == "remove":
                membership.set_admin_role(False, user)
                messages.success(
                    request,
                    _("%(name)s a été retiré(e) des administrateurs de cette structure.")
                    % {"name": target_member.get_full_name()},
                )
                siae.remove_admin_email(target_member).send()
                kill_sessions_for_user(membership.user.pk)
            membership.save()
        else:
            raise PermissionDenied
        return HttpResponseRedirect(reverse_lazy("siaes_views:members"))

    context = {
        "action": action,
        "siae": siae,
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
        messages.success(request, _("Mise à jour du blocage des candidatures effectuée !"))
        return HttpResponseRedirect(reverse_lazy("dashboard:index"))

    context = {"siae": siae, "form": form}

    return render(request, template_name, context)
