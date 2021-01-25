from django.http import HttpResponsePermanentRedirect


class NewDnsRedirectMiddleware:
    """
    Redirect to new domain names.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        host = request.get_host().partition(":")[0]
        new_host = None

        if host == "inclusion.beta.gouv.fr" or host == "emploi.inclusion.beta.gouv.fr":
            new_host = "emplois.inclusion.beta.gouv.fr"

        elif host == "demo.inclusion.beta.gouv.fr":
            new_host = "demo.emplois.inclusion.beta.gouv.fr"

        elif host == "staging.inclusion.beta.gouv.fr":
            new_host = "staging.emplois.inclusion.beta.gouv.fr"

        if new_host:
            return HttpResponsePermanentRedirect(f"https://{new_host}{request.get_full_path()}")

        return self.get_response(request)
