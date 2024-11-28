from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponseRedirect
from django.urls import reverse


@login_not_required
def home(request):
    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse("dashboard:index"))
    return HttpResponseRedirect(reverse("search:employers_home"))
