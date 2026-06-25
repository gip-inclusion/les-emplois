from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponseRedirect

from itou.utils.readonly import readonly_view


@login_not_required
@readonly_view
def security_txt(request):
    return HttpResponseRedirect("https://inclusion.gouv.fr/.well-known/security.txt")
