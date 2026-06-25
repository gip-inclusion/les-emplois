from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponseRedirect
from django.urls import reverse

from itou.utils.readonly import readonly_view


@login_not_required
@readonly_view
def home(request):
    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse("dashboard:index"))
    return HttpResponseRedirect(reverse("search:employers_home"))
