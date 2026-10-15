"""
Functions used in organization views.
"""

import logging

from allauth.account.views import redirect
from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.forms.boundfield import format_html
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.generic import DetailView, ListView

from itou.common_apps.organizations import transfer
from itou.common_apps.organizations.admin import OrgChooseFieldsToTransfer, SelectTargetOrgForm
from itou.companies.models import Company
from itou.prescribers.models import PrescriberOrganization
from itou.utils.admin import bulk_add_support_remark_to_objs
from itou.utils.pagination import ItouPaginator
from itou.www.invitations_views.views import MAX_PENDING_INVITATION


logger = logging.getLogger(__name__)


class BaseMemberList(UserPassesTestMixin, ListView):
    paginate_by = 50  # Most organizations will have only one page
    paginator_class = ItouPaginator

    def setup(self, request, *args, **kwargs):
        # test_func is called in super().dispatch so we can jobseeker here and current_organization won't exist
        self.organization = getattr(request, "current_organization", None)
        if self.organization is None:
            raise PermissionDenied
        super().setup(request, *args, **kwargs)

    def get_queryset(self):
        return (
            self.organization.memberships.select_related("user")
            .all()
            .order_by("user__last_name", "user__first_name", "pk")
        )

    def get_invitation_url(self):
        raise NotImplementedError

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        members_stats = self.get_queryset().aggregate(
            total_count=Count("pk"),
            admin_count=Count("pk", filter=Q(is_admin=True)),
        )
        pending_invitations = self.organization.invitations.pending()

        context["members_stats"] = members_stats
        context["pending_invitations"] = pending_invitations
        context["invitation_url"] = (
            self.get_invitation_url() if len(pending_invitations) < MAX_PENDING_INVITATION else None
        )
        context["active_admin_members"] = self.organization.active_admin_members
        return context


def deactivate_org_member(request, user_id, *, success_url, template_name):
    if not request.is_current_organization_admin or request.user.pk == user_id:
        raise PermissionDenied

    membership = get_object_or_404(
        request.current_organization.memberships.select_related("user"),
        user_id=user_id,
        is_active=True,
    )

    if request.method == "POST":
        request.current_organization.deactivate_membership(membership, updated_by=request.user)
        messages.success(
            request,
            f"{membership.user.get_inverted_full_name()} a été retiré(e) des membres actifs de cette structure.",
        )
        return HttpResponseRedirect(success_url)

    context = {
        "structure": request.current_organization,
        "target_member": membership.user,
    }

    return render(request, template_name, context)


def update_org_admin_role(request, action, user_id, *, success_url, template_name):
    if not request.is_current_organization_admin or request.user.pk == user_id:
        raise PermissionDenied

    membership = get_object_or_404(
        request.current_organization.memberships.select_related("user"),
        user_id=user_id,
        is_active=True,
    )

    if request.method == "POST":
        match action:
            case "add":
                admin = True
                action_label = "ajouté(e) aux"
            case "remove":
                admin = False
                action_label = "retiré(e) des"
            case _:
                raise ValueError(f"Unknown {action=}")
        request.current_organization.set_admin_role(membership, admin, updated_by=request.user)
        messages.success(
            request,
            f"{membership.user.get_inverted_full_name()} a été {action_label} administrateurs de cette structure.",
        )
        return HttpResponseRedirect(success_url)

    context = {
        "action": action,
        "structure": request.current_organization,
        "target_member": membership.user,
    }
    return render(request, template_name, context)


class BaseTransferView(UserPassesTestMixin, DetailView):
    pk_url_kwarg = "from_org_pk"
    template_name = "admin/organizations/transfer_org.html"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.transfer_data = None
        self.to_org = None
        self.to_org_model_label = None
        self.to_org_model_label_fr = None
        self.transfer_fields = []
        self.transfer_specs = {}
        self.transfer_data = {}
        self.related_fields = []
        self.model_admin = None

    def test_func(self):
        return self.model_admin.has_change_permission(self.request)

    def setup(self, request, to_org_pk=None, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.to_org = get_object_or_404(self.model, pk=to_org_pk) if to_org_pk else None
        is_company_transfer = self.model is Company
        self.org_model_label = self.model._meta.label_lower.split(".")[-1]
        self.org_model_label_fr = "entreprise" if is_company_transfer else "organisation prescriptrice"
        self.transfer_fields = (
            transfer.COMPANY_TRANSFER_FIELDS if is_company_transfer else transfer.PRESCRIBERORG_TRANSFER_FIELDS
        )
        self.transfer_specs = (
            transfer.COMPANY_TRANSFER_SPECS if is_company_transfer else transfer.PRESCRIBERORG_TRANSFER_SPECS
        )
        self.model_admin = kwargs["model_admin"]

    def get_transfer_data(self):
        if not self.transfer_data:
            for transfer_field in self.transfer_fields:
                spec = self.transfer_specs[transfer_field]
                if model_field := spec.get("model_field"):
                    from_data = [getattr(self.object, model_field.name)]
                else:
                    from_data = transfer.get_transfer_queryset(self.object, self.to_org, spec)
                self.transfer_data[transfer_field] = {
                    "data": from_data,
                }
        return self.transfer_data

    def get_form(self):
        if self.to_org:
            fields_choices = []
            transfer_data = self.get_transfer_data()
            for transfer_field in self.transfer_fields:
                spec = self.transfer_specs[transfer_field]
                if model_field := spec.get("model_field"):
                    if transfer_data[transfer_field]["data"] == [getattr(self.to_org, model_field.name)]:
                        transfer_data[transfer_field]["data"] = None
                    else:
                        fields_choices.append((transfer_field.value, transfer_field.label))
                elif from_data := transfer_data[transfer_field]["data"]:
                    s = "s" if len(from_data) > 1 else ""
                    fields_choices.append(
                        (
                            transfer_field.value,
                            f"{transfer_field.label} ({len(from_data)} objet{s} à transférer)",
                        )
                    )
                    self.related_fields.append(transfer_field)
            return OrgChooseFieldsToTransfer(
                fields_choices=sorted(fields_choices, key=lambda field: field[1]),
                data=self.request.POST or None,
            )
        else:
            return SelectTargetOrgForm(
                from_org=self.object,
                admin_site=self.model_admin.admin_site,
                data=self.request.POST or None,
            )

    def get_redirect_url(self):
        raise NotImplementedError

    def get_success_url(self):
        raise NotImplementedError

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = self.get_form()
        if form.is_valid():
            if self.to_org is None:
                self.to_org = form.cleaned_data["to_org"]
                return redirect(self.get_redirect_url())
            else:
                fields_to_transfer = form.cleaned_data["fields_to_transfer"]
                disable_from_org = form.cleaned_data["disable_from_org"]
                post_transfer_action = disable_from_org and transfer.PostTransferAction.DEACTIVATE or None
                # If every related field is to be transferred to the target org, the source org should be deleted
                if (
                    all([field in fields_to_transfer for field in self.related_fields])
                    and self.model is PrescriberOrganization
                ):
                    post_transfer_action = transfer.PostTransferAction.DELETE
                # In case the target org adopts the source org's name,
                # save the old name to avoid weird displays
                to_org_display = str(self.to_org)
                try:
                    reporter = transfer.transfer_org_data(
                        self.object,
                        self.to_org,
                        fields_to_transfer=fields_to_transfer,
                        post_transfer_action=post_transfer_action,
                    )
                except transfer.TransferError as e:
                    messages.error(request, e.args[0])
                else:
                    summary_lines = [
                        "-" * 20,
                        f"Transfert du {timezone.now():%Y-%m-%d %H:%M:%S} effectué par {self.request.user} ",
                        f"de l'{self.org_model_label_fr} {self.object.pk} vers {self.to_org.pk}:",
                    ]
                    for report_field, items in reporter.changes.items():
                        if items:
                            summary_lines.extend([f"- {report_field.label}:"] + [f"  * {item}" for item in items])
                    summary_lines += ["-" * 20]
                    summary_text = "\n".join(summary_lines)
                    bulk_add_support_remark_to_objs([self.object, self.to_org], summary_text)
                    message = format_html(
                        "Transfert effectué avec succès de l’{org_label} {from_org} vers {to_org}.",
                        org_label=self.org_model_label_fr,
                        from_org=self.object,
                        to_org=f"{to_org_display} (désormais {self.to_org})"
                        if to_org_display != str(self.to_org)
                        else self.to_org,
                    )
                    messages.info(self.request, message)
                    logger.info(
                        "staff user=%d transferred %s=%d to %s=%d with fields_to_transfer=%s, post_transfer_action=%s",
                        self.request.user.pk,
                        self.org_model_label,
                        self.object.pk,
                        self.org_model_label,
                        self.to_org.pk,
                        fields_to_transfer,
                        getattr(post_transfer_action, "value", None),
                    )
                    if post_transfer_action is transfer.PostTransferAction.DELETE:
                        self.object = None
                    return redirect(self.get_success_url())
        return self.render_to_response(self.get_context_data(**kwargs))

    def get_context_data(self, **kwargs):
        title = f"Transfert des données de '{self.object}' [{self.object.kind}]"
        if self.to_org:
            title += f" vers '{self.to_org}' [{self.to_org.kind}]"
        return self.model_admin.admin_site.each_context(self.request) | {
            "from_org": self.object,
            "to_org": self.to_org,
            "media": self.model_admin.media,
            "opts": self.model_admin.opts,
            "form": self.get_form(),
            "transfer_data": self.get_transfer_data(),
            "title": title,
            "subtitle": None,
            "has_view_permission": self.model_admin.has_view_permission(self.request),
        }
