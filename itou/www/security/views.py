from django.http import HttpResponseRedirect


def security_txt(request):
    return HttpResponseRedirect("https://inclusion.gouv.fr/.well-known/security.txt")
