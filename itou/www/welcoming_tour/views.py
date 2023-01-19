from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from itou.users.enums import UserKind


@login_required
def index(request):
    user = request.user
    template_name = "welcoming_tour/job_seeker.html"

    if user.kind == UserKind.SIAE_STAFF:
        template_name = "welcoming_tour/siae_staff.html"

    if user.kind == UserKind.PRESCRIBER:
        template_name = "welcoming_tour/prescriber.html"

    user.has_completed_welcoming_tour = True
    user.save()

    return render(request, template_name)
