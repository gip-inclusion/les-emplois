from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse_lazy
from django.utils.translation import ugettext as _

from allauth.account.views import PasswordChangeView

from itou.siaes.models import Siae
from itou.utils.urls import get_safe_url
from itou.www.dashboard.forms import EditUserInfoForm


@login_required
def dashboard(request, template_name="dashboard/dashboard.html"):

    user_is_admin = False
    if request.user.is_siae_staff:
        current_siae_pk = request.session.get(settings.ITOU_SESSION_CURRENT_SIAE_KEY)
        current_siae = request.user.siae_set.get(pk=current_siae_pk)
        user_is_admin = current_siae.has_active_admin_member(request.user)
    context = {"user_is_admin": user_is_admin}
    return render(request, template_name, context)


class ItouPasswordChangeView(PasswordChangeView):
    """
    https://github.com/pennersr/django-allauth/issues/468
    """

    success_url = reverse_lazy("dashboard:index")


password_change = login_required(ItouPasswordChangeView.as_view())


@login_required
def edit_user_info(request, template_name="dashboard/edit_user_info.html"):
    """
    Edit a user.
    """

    dashboard_url = reverse_lazy("dashboard:index")
    prev_url = get_safe_url(request, "prev_url", fallback_url=dashboard_url)
    form = EditUserInfoForm(instance=request.user, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Mise à jour de vos informations effectuée !"))
        success_url = get_safe_url(request, "success_url", fallback_url=dashboard_url)
        return HttpResponseRedirect(success_url)

    context = {"form": form, "prev_url": prev_url}
    return render(request, template_name, context)


@login_required
def switch_siae(request):
    """
    Switch to the dashboard of another SIAE of the same SIREN
    """

    dashboard_url = reverse_lazy("dashboard:index")
    prev_url = get_safe_url(request, "prev_url", fallback_url=dashboard_url)

    if request.method == "POST" and request.user.is_siae_staff:
        siae = Siae.active_objects.get(pk=request.POST.get("siae_id", ""))
        if siae in request.user.siae_set.all():
            request.session[settings.ITOU_SESSION_CURRENT_SIAE_KEY] = siae.pk
            messages.success(
                request,
                _("Je travaille maintenant sur la SIAE {}".format(siae.display_name)),
            )
            return HttpResponseRedirect(dashboard_url)

    messages.error(
        request,
        _(
            "Une erreur inattendue s'est produite. Vous pouvez retenter votre dernière action."
        ),
    )
    return HttpResponseRedirect(prev_url)
