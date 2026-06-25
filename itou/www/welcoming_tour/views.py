from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from itou.utils.readonly import http_methods


@http_methods(db_write=["GET", "HEAD"])
def index(request):
    user = request.user

    template_name = None
    if request.user.is_job_seeker:
        template_name = "welcoming_tour/job_seeker.html"
    elif request.from_employer:
        template_name = "welcoming_tour/employer.html"
    elif request.from_prescriber:
        template_name = "welcoming_tour/prescriber.html"

    if template_name:
        user.has_completed_welcoming_tour = True
        user.save()
        return render(request, template_name)
    else:
        return HttpResponseRedirect(reverse("dashboard:index"))
