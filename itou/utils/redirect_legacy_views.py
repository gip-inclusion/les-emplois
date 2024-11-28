from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponsePermanentRedirect


@login_not_required
def redirect_siaes_views(request, *args, **kwargs):
    return HttpResponsePermanentRedirect(request.get_full_path().replace("/siae", "/company", 1))
