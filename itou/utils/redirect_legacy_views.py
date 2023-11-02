from django.http import HttpResponsePermanentRedirect


def redirect_siaes_views(request, *args, **kwargs):
    return HttpResponsePermanentRedirect(request.get_full_path().replace("/siae", "/company", 1))
