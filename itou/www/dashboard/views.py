from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.utils.translation import ugettext as _

from allauth.account.views import PasswordChangeView
from itou.jobs.models import Appellation
from itou.siaes.models import Siae


@login_required
def dashboard(request, template_name="dashboard/dashboard.html"):

    context = {}
    return render(request, template_name, context)


class ItouPasswordChangeView(PasswordChangeView):
    """
    https://github.com/pennersr/django-allauth/issues/468
    """

    success_url = reverse_lazy("dashboard:index")


password_change = login_required(ItouPasswordChangeView.as_view())


@login_required
def configure_jobs(request, template_name="dashboard/configure_jobs.html"):
    """
    Configure an SIAE's jobs.
    """
    siret = request.session[settings.ITOU_SESSION_CURRENT_SIAE_KEY]
    queryset = Siae.active_objects.prefetch_jobs_through().member_required(request.user)
    siae = get_object_or_404(queryset, siret=siret)

    if request.method == "POST":

        current_codes = set(
            siae.jobs_through.values_list("appellation__code", flat=True)
        )
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
                    "is_active": bool(request.POST.get(f"is_active-{code}"))
                }
                siae.jobs.add(appellation, through_defaults=through_defaults)

            # Delete.
            if codes_to_delete:
                appellations = Appellation.objects.filter(code__in=codes_to_delete)
                siae.jobs.remove(*appellations)

            # Update.
            for job_through in siae.jobs_through.filter(
                appellation__code__in=codes_to_update
            ):
                is_active = bool(
                    request.POST.get(f"is_active-{job_through.appellation.code}")
                )
                if job_through.is_active != is_active:
                    job_through.is_active = is_active
                    job_through.save()

            messages.success(request, _("Mise à jour effectuée !"))
            return HttpResponseRedirect(reverse_lazy("dashboard:configure_jobs"))

    context = {"siae": siae}
    return render(request, template_name, context)
