from django.contrib import admin, messages
from django.contrib.auth import get_permission_codename
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.translation import gettext as _

from itou.approvals.admin_forms import ManuallyAddApprovalForm
from itou.approvals.models import Approval
from itou.job_applications.models import JobApplication, JobApplicationWorkflow


@transaction.atomic
def manually_add_approval(
    request,
    model_admin,
    job_application_id,
    template_name="admin/approvals/manually_add_approval.html",
):
    """
    Custom admin view to manually add an approval pre-filled with some FK.

    https://docs.djangoproject.com/en/dev/ref/contrib/admin/#adding-views-to-admin-sites
    https://github.com/django/django/blob/master/django/contrib/admin/templates/admin/change_form.html
    """

    opts = model_admin.model._meta
    app_label = opts.app_label
    codename = get_permission_codename("add", opts)
    has_perm = request.user.has_perm(f"{app_label}.{codename}")

    if not has_perm:
        raise PermissionDenied

    queryset = JobApplication.objects.select_related(
        "job_seeker",
        "sender",
        "sender_siae",
        "sender_prescriber_organization",
        "to_siae",
    )
    job_application = get_object_or_404(
        queryset,
        pk=job_application_id,
        state=JobApplicationWorkflow.STATE_ACCEPTED,
        approval=None,
    )

    initial = {
        "start_at": job_application.hiring_start_at,
        "end_at": Approval.get_default_end_date(job_application.hiring_start_at),
        "number": Approval.get_next_number(job_application.hiring_start_at),
        "user": job_application.job_seeker.pk,
        "created_by": request.user.pk,
    }
    form = ManuallyAddApprovalForm(initial=initial, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        approval = form.save()
        job_application.approval = approval
        job_application.save()
        job_application.send_approval_number_by_email_manually(deliverer=request.user)
        messages.success(
            request,
            _(
                f"Le PASS IAE {approval.number_with_spaces} a bien été créé et envoyé par e-mail."
            ),
        )
        return HttpResponseRedirect(reverse("admin:approvals_approval_changelist"))

    fieldsets = [(None, {"fields": list(form.base_fields)})]
    adminForm = admin.helpers.AdminForm(form, fieldsets, {})

    admin_site = model_admin.admin_site

    context = {
        "add": True,
        "adminform": adminForm,
        "admin_site": admin_site.name,
        "app_label": app_label,
        "errors": admin.helpers.AdminErrorList(form, {}),
        "form": form,
        "job_application": job_application,
        "opts": opts,
        "title": _("Ajout manuel d'un numéro d'agrément"),
        **admin_site.each_context(request),
    }
    return render(request, template_name, context)
