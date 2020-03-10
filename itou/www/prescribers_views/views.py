from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.utils.translation import gettext as _

from itou.prescribers.models import PrescriberOrganization
from itou.www.prescribers_views.forms import (
    CreatePrescriberOrganizationForm,
    EditPrescriberOrganizationForm,
)


@login_required
def create_organization(request, template_name="prescribers/create_organization.html"):
    """
    Create a prescriber organization.
    """

    if not request.user.is_prescriber:
        raise PermissionDenied

    form = CreatePrescriberOrganizationForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.save(request.user)
        messages.success(request, _("Création effectuée !"))
        return HttpResponseRedirect(reverse_lazy("dashboard:index"))

    context = {"form": form}
    return render(request, template_name, context)


@login_required
def edit_organization(request, template_name="prescribers/edit_organization.html"):
    """
    Edit a prescriber organization.
    """
    pk = request.session[settings.ITOU_SESSION_CURRENT_PRESCRIBER_ORG_KEY]
    queryset = PrescriberOrganization.objects.member_required(request.user)
    organization = get_object_or_404(queryset, pk=pk)

    form = EditPrescriberOrganizationForm(
        instance=organization, data=request.POST or None
    )

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Mise à jour effectuée !"))
        return HttpResponseRedirect(reverse_lazy("dashboard:index"))

    context = {"form": form, "organization": organization}
    return render(request, template_name, context)
