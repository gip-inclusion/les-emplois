from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.utils.translation import ugettext as _

from itou.job_applications.forms import JobRequestForm
from itou.siaes.models import Siae
from itou.utils.urls import get_safe_url


@user_passes_test(
    lambda user: user.is_job_seeker, login_url="/", redirect_field_name=None
)
def send_job_request(request, siret, template_name="job_applications/job_request.html"):
    """
    Submit a job request.
    """

    next_url = get_safe_url(request, "next")

    # if not request.user.can_postulate():
    #     current_url = request.build_absolute_uri()

    queryset = Siae.active_objects.prefetch_jobs_through()
    siae = get_object_or_404(queryset, siret=siret)

    form = JobRequestForm(data=request.POST or None, user=request.user, siae=siae)

    if request.method == "POST" and form.is_valid():
        job_request = form.save()
        job_request.send(user=request.user)
        messages.success(request, _("Votre candidature a bien été envoyée !"))
        return HttpResponseRedirect(next_url)

    context = {"siae": siae, "form": form, "next_url": next_url}
    return render(request, template_name, context)
