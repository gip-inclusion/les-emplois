from django.http import HttpResponseRedirect
from django.urls import reverse


def home(request):
    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse("dashboard:index"))
    return HttpResponseRedirect(reverse("search:employers_home"))
