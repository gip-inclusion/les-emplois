from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponseRedirect
from django.urls import reverse

from itou.utils.readonly import readonly_view
from itou.www.constants import REDIRECTED_FROM_OLD_DOMAIN_QUERY_PARAM


@login_not_required
@readonly_view
def home(request):
    if request.user.is_authenticated:
        url = reverse("dashboard:index")
    else:
        url = reverse("search:home")
    # Handle REDIRECTED_FROM_OLD_DOMAIN_QUERY_PARAM (and only that,
    # there is no use case for any other query string parameter).
    if REDIRECTED_FROM_OLD_DOMAIN_QUERY_PARAM in request.GET:
        url += f"?{REDIRECTED_FROM_OLD_DOMAIN_QUERY_PARAM}=1"
    return HttpResponseRedirect(url)
