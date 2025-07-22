"""
Custom admin views.

We should keep those to a minimum to avoid a future maintenance nightmare.

https://docs.djangoproject.com/en/dev/ref/contrib/admin/#adding-views-to-admin-sites
https://github.com/django/django/blob/master/django/contrib/admin/templates/admin/change_form.html
"""

import logging
from collections import defaultdict

from django.contrib import admin, messages
from django.contrib.auth import get_permission_codename
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone

from itou.approvals.admin_forms import ManuallyAddApprovalFromJobApplicationForm
from itou.approvals.enums import Origin
from itou.approvals.models import Approval, CancelledApproval, Prolongation, Suspension
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplication
from itou.utils.admin import add_support_remark_to_obj
from itou.utils.apis import enums as api_enums
from itou.utils.emails import get_email_text_template
from itou.utils.urls import add_url_params, get_absolute_url


logger = logging.getLogger("itou.approvals.admin")


def manually_add_approval(
    request, model_admin, job_application_id, template_name="admin/approvals/manually_add_approval.html"
):
    """
    Custom admin view to manually add an approval.
    """

    admin_site = model_admin.admin_site
    opts = model_admin.model._meta
    app_label = opts.app_label
    has_perm = request.user.has_perm(f"{app_label}.handle_manual_approval_requests")

    if not has_perm:
        raise PermissionDenied

    queryset = JobApplication.objects.select_related(
        "job_seeker", "sender", "sender_company", "sender_prescriber_organization", "to_company"
    )
    job_application = get_object_or_404(
        queryset,
        pk=job_application_id,
        state=JobApplicationState.ACCEPTED,
        approval=None,
        approval_manually_refused_at=None,
        approval_manually_refused_by=None,
        approval_number_sent_by_email=False,
    )

    if job_application.eligibility_diagnosis is None:
        messages.error(
            request, "Impossible de créer un PASS IAE car la candidature n'a pas de diagnostic d'éligibilité."
        )
        return HttpResponseRedirect(reverse("admin:approvals_approval_changelist"))

    initial = {
        "start_at": job_application.hiring_start_at,
        "end_at": Approval.get_default_end_date(job_application.hiring_start_at),
    }
    form = ManuallyAddApprovalFromJobApplicationForm(initial=initial, data=request.POST or None)
    fieldsets = [(None, {"fields": list(form.base_fields)})]
    adminForm = admin.helpers.AdminForm(form, fieldsets, {})

    if request.method == "POST" and form.is_valid():
        form.instance.user = job_application.job_seeker
        form.instance.origin = Origin.ADMIN
        form.instance.created_by = request.user
        form.instance.eligibility_diagnosis = job_application.eligibility_diagnosis
        for field, value in Approval.get_origin_kwargs(job_application).items():
            setattr(form.instance, field, value)
        approval = form.save()
        job_application.approval = approval
        job_application.manually_deliver_approval(delivered_by=request.user)
        messages.success(request, f"Le PASS IAE {approval.number_with_spaces} a bien été créé et envoyé par e-mail.")
        return HttpResponseRedirect(reverse("admin:approvals_approval_changelist"))

    context = {
        "add": True,
        "adminform": adminForm,
        "admin_site": admin_site.name,
        "app_label": app_label,
        "errors": admin.helpers.AdminErrorList(form, {}),
        "form": form,
        "job_application": job_application,
        "media": model_admin.media,
        "opts": opts,
        "title": "Ajout manuel d'un numéro d'agrément",
        "subtitle": None,
        "has_view_permission": model_admin.has_view_permission(request),
        **admin_site.each_context(request),
    }
    return render(request, template_name, context)


def manually_refuse_approval(
    request, model_admin, job_application_id, template_name="admin/approvals/manually_refuse_approval.html"
):
    """
    Custom admin view to manually refuse an approval (in the case of a job seeker in waiting period).
    """

    admin_site = model_admin.admin_site
    opts = model_admin.model._meta
    app_label = opts.app_label
    has_perm = request.user.has_perm(f"{app_label}.handle_manual_approval_requests")

    if not has_perm:
        raise PermissionDenied

    queryset = JobApplication.objects.select_related(
        "job_seeker", "sender", "sender_company", "sender_prescriber_organization", "to_company"
    )
    job_application = get_object_or_404(
        queryset,
        pk=job_application_id,
        state=JobApplicationState.ACCEPTED,
        approval=None,
        approval_manually_delivered_by=None,
        approval_number_sent_by_email=False,
    )

    if request.method == "POST" and request.POST.get("confirm") == "yes":
        job_application.manually_refuse_approval(refused_by=request.user)
        messages.success(request, "Délivrance du PASS IAE refusée.")
        return HttpResponseRedirect(reverse("admin:approvals_approval_changelist"))

    # Display a preview of the email that will be send.
    email_subject_template = get_email_text_template(
        "approvals/email/refuse_manually_subject.txt", {"job_application": job_application}
    )
    email_body_template = get_email_text_template(
        "approvals/email/refuse_manually_body.txt",
        {
            "job_application": job_application,
            "job_application_url": get_absolute_url(
                reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
            ),
            "search_url": get_absolute_url(reverse("search:prescribers_home")),
        },
    )

    context = {
        "add": True,
        "admin_site": admin_site.name,
        "app_label": app_label,
        "email_body_template": email_body_template,
        "email_subject_template": email_subject_template,
        "job_application": job_application,
        "media": model_admin.media,
        "opts": opts,
        "title": "Confirmer le refus manuel d'un numéro d'agrément",
        "subtitle": None,
        "has_view_permission": model_admin.has_view_permission(request),
        **admin_site.each_context(request),
    }
    return render(request, template_name, context)


def _clip_approval_dependency(approval, model, end_date, acting_user):
    _, deletions = model.objects.filter(approval=approval, start_at__gte=end_date).delete()
    if deletions:
        logger.info(
            "Terminating approval pk=%(approval_id)d, deleting %(deletions)d future %(model_name)s.",
            {
                "approval_id": approval.pk,
                "deletions": deletions[model._meta.label],
                "model_name": model._meta.label,
            },
        )
    try:
        obj = model.objects.in_progress().filter(approval=approval).get()
    except model.DoesNotExist:
        pass
    else:
        logger.info(
            "Terminating approval pk=%(approval_id)d, "
            "setting %(model_name)s pk=%(model_id)d end_at=%(end_at)s "
            "(was %(initial_end_at)s).",
            {
                "approval_id": approval.pk,
                "model_name": obj._meta.label,
                "model_id": obj.pk,
                "end_at": end_date,
                "initial_end_at": obj.end_at,
            },
        )
        obj.end_at = end_date
        obj.updated_by = acting_user
        obj.save(update_fields=["end_at", "updated_at", "updated_by"])


def terminate_approval(request, model_admin, approval_id):
    opts = model_admin.model._meta
    app_label = opts.app_label
    codename = get_permission_codename("change", opts)
    if not request.user.has_perm(f"{app_label}.{codename}"):
        raise PermissionDenied

    new_end = timezone.localdate()
    approval = get_object_or_404(Approval, pk=approval_id, end_at__gte=new_end)
    _clip_approval_dependency(approval, Prolongation, new_end, request.user)
    _clip_approval_dependency(approval, Suspension, new_end, request.user)
    logger.info(
        "Terminating approval pk=%(approval_id)d, end_at=%(end_at)s (was %(initial_end_at)s).",
        {
            "approval_id": approval.pk,
            "initial_end_at": approval.end_at,
            "end_at": new_end,
        },
    )
    approval.end_at = new_end
    approval.save(update_fields=["end_at", "updated_at"])
    add_support_remark_to_obj(approval, f"{new_end} : PASS IAE clôturé par {request.user.get_full_name()}.")
    return HttpResponseRedirect(reverse("admin:approvals_approval_change", kwargs={"object_id": approval.pk}))


def _compute_send_approvals_to_pe_stats(model, list_url):
    today = timezone.localdate()

    def _format_value(value, total):
        if not value:
            return str(value)
        if not total:
            return "-"
        return f"{value} ({100 * value / total:.2f} %)"

    counts = model.objects.aggregate(
        total=Count("pk"),
        # Count by status
        pe_notify_pending=Count("pk", filter=Q(pe_notification_status=api_enums.PEApiNotificationStatus.PENDING)),
        pe_notify_ready=Count("pk", filter=Q(pe_notification_status=api_enums.PEApiNotificationStatus.READY)),
        pe_notify_should_retry=Count(
            "pk", filter=Q(pe_notification_status=api_enums.PEApiNotificationStatus.SHOULD_RETRY)
        ),
        pe_notify_error=Count("pk", filter=Q(pe_notification_status=api_enums.PEApiNotificationStatus.ERROR)),
        pe_notify_success=Count("pk", filter=Q(pe_notification_status=api_enums.PEApiNotificationStatus.SUCCESS)),
        # More infos on PENDING
        pe_notify_pending_in_future=Count(
            "pk",
            filter=Q(pe_notification_status=api_enums.PEApiNotificationStatus.PENDING, start_at__gt=today),
        ),
    )
    errors_infos = defaultdict(lambda: defaultdict(dict))
    for endpoint, exit_code, count in (
        model.objects.filter(pe_notification_status=api_enums.PEApiNotificationStatus.ERROR)
        .values_list("pe_notification_endpoint", "pe_notification_exit_code")
        .annotate(count=Count("pk"))
    ):
        errors_infos[endpoint].setdefault("value", 0)
        errors_infos[endpoint]["value"] += count
        errors_infos[endpoint]["infos"][exit_code] = {"value": count}
    # Prevent further defaulting to enable its use in Django template
    errors_infos.default_factory = None
    # Adapt dictionnary value to add percentages
    for end_point, end_point_infos in errors_infos.items():
        end_point_url_params = {"pe_notification_status": "notification_error", "pe_notification_endpoint": end_point}
        for exit_code, exit_code_infos in end_point_infos["infos"].items():
            exit_code_infos["value"] = _format_value(exit_code_infos["value"], end_point_infos["value"])
            if exit_code is None:
                exit_code_url_params = {**end_point_url_params, "pe_notification_exit_code__isnull": 1}
            else:
                exit_code_url_params = {**end_point_url_params, "pe_notification_exit_code": exit_code}
            exit_code_infos["url"] = add_url_params(list_url, exit_code_url_params)
        end_point_infos["value"] = _format_value(end_point_infos["value"], counts["pe_notify_error"])
        end_point_infos["url"] = add_url_params(list_url, end_point_url_params)

    stats = {
        "name": model._meta.verbose_name_plural,
        "total": counts["total"],
        "infos": {
            "En attente": {
                "value": _format_value(counts["pe_notify_pending"], counts["total"]),
                "infos": {
                    "Démarre dans le futur": {
                        "value": _format_value(counts["pe_notify_pending_in_future"], counts["pe_notify_pending"]),
                        "url": add_url_params(
                            list_url, {"pe_notification_status": "notification_pending", "start_at__gt": today}
                        ),
                    },
                },
                "url": add_url_params(list_url, {"pe_notification_status": "notification_pending"}),
            },
            "Prêt à envoyer": {
                "value": _format_value(counts["pe_notify_ready"], counts["total"]),
                "infos": {},
                "url": add_url_params(list_url, {"pe_notification_status": "notification_ready"}),
            },
            "À réessayer": {
                "value": _format_value(counts["pe_notify_should_retry"], counts["total"]),
                "infos": {},
                "url": add_url_params(list_url, {"pe_notification_status": "notification_should_retry"}),
            },
            "En erreur": {
                "value": _format_value(counts["pe_notify_error"], counts["total"]),
                "infos": errors_infos,
                "url": add_url_params(list_url, {"pe_notification_status": "notification_error"}),
            },
            "Succès": {
                "value": _format_value(counts["pe_notify_success"], counts["total"]),
                "infos": {},
                "url": add_url_params(list_url, {"pe_notification_status": "notification_success"}),
            },
        },
    }
    return stats


def send_approvals_to_pe_stats(request):
    context_data = {
        **admin.site.each_context(request),
        "title": "État de synchronisation avec France Travail",
        "subtitle": None,
        "stats": [
            _compute_send_approvals_to_pe_stats(Approval, list_url=reverse("admin:approvals_approval_changelist")),
            _compute_send_approvals_to_pe_stats(
                CancelledApproval, list_url=reverse("admin:approvals_cancelledapproval_changelist")
            ),
        ],
    }
    return render(request, "admin/approvals/send_approvals_to_pe_stats.html", context_data)
