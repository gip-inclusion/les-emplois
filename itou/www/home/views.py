import logging

from django.http import HttpResponseRedirect
from django.urls import reverse


logger = logging.getLogger(__name__)


def home(request):
    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse("dashboard:index"))
    return HttpResponseRedirect(reverse("search:siaes_home"))


def trigger_error(request):
    if request.POST:
        raise Exception("{} error: {}".format(request.POST.get("status_code"), request.POST.get("error_message")))

    print(1 / 0)  # Should raise a ZeroDivisionError.
