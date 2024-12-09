from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.deprecation import MiddlewareMixin
from django.utils.http import urlencode

from itou.users.enums import IdentityProvider
from itou.users.models import User


class ProConnectLoginMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if "proconnect_login" not in request.GET:
            return

        query_params = request.GET.copy()
        query_params.pop("proconnect_login")
        username = query_params.pop("username", [None])
        new_url = (
            f"{request.path}?{urlencode({k: v for k, v in query_params.items() if v})}"
            if query_params
            else request.path
        )

        if request.user.is_authenticated:
            return HttpResponseRedirect(new_url)

        try:
            user = User.objects.get(username=username[0], identity_provider=IdentityProvider.PRO_CONNECT.value)
            return HttpResponseRedirect(
                reverse("pro_connect:authorize") + f"?user_kind={user.kind}&next_url={new_url}"
            )
        except User.DoesNotExist:
            return HttpResponseRedirect(reverse("signup:choose_user_kind") + f"?next_url={new_url}")
