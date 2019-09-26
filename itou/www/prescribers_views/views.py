from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse_lazy
from django.utils.translation import ugettext as _

from itou.www.prescribers_views.forms import CreatePrescriberOrganizationForm


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
