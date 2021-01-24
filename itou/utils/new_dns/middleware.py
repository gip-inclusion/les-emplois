from django.contrib import messages
from django.http import HttpResponsePermanentRedirect
from django.utils import safestring
from django.utils.translation import gettext as _


class NewDnsRedirectMiddleware:
    """
    Redirect to new domain names.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        host = request.get_host().partition(":")[0]
        new_host = None

        if host == "inclusion.beta.gouv.fr":
            new_host = "emplois.inclusion.beta.gouv.fr"

        elif host == "demo.inclusion.beta.gouv.fr":
            new_host = "demo.emplois.inclusion.beta.gouv.fr"

        elif host == "staging.inclusion.beta.gouv.fr":
            new_host = "staging.emplois.inclusion.beta.gouv.fr"

        if new_host:
            message = _(f"Notre nom de domaine change. Nous vous accueillons maintenant sur <b>{new_host}</b>")
            message = safestring.mark_safe(message)
            messages.warning(request, message)
            return HttpResponsePermanentRedirect(f"https://{new_host}{request.get_full_path()}")

        return self.get_response(request)
