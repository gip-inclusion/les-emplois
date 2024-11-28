from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponseRedirect


@login_not_required
def security_txt(request):
    return HttpResponseRedirect("https://inclusion.gouv.fr/.well-known/security.txt")
