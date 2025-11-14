import logging

import jwt
from django.conf import settings
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.deprecation import MiddlewareMixin

from itou.users.enums import IdentityProvider, UserKind
from itou.users.models import User


logger = logging.getLogger(__name__)


class ProConnectLoginMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if "proconnect_login" not in request.GET:
            return

        query_params = request.GET.copy()
        [token] = query_params.pop("proconnect_login")
        email = None
        username = None

        # FIXME: Remove this when la communauté uses the new workflow
        if token == "true":
            [username] = query_params.pop("username", [None])
        else:
            try:
                decoded_data = jwt.decode(
                    token,
                    key=settings.PRO_CONNECT_AUTO_LOGIN_KEY,
                    algorithms=["HS256"],
                    # TODO: Remove once https://github.com/jpadilla/pyjwt/issues/939 is fixed
                    options={"verify_iat": False},
                )
                email = decoded_data["email"]
            except jwt.InvalidTokenError:
                logger.warning("Invalid proconnect_login token")

        new_url = f"{request.path}?{query_params.urlencode()}" if query_params else request.path

        # TODO: check user email once we droped username parameter
        if request.user.is_authenticated:
            return HttpResponseRedirect(new_url)

        try:
            # FIXME: Remove this when la communauté uses the new workflow
            if username:
                user = User.objects.get(username=username, identity_provider=IdentityProvider.PRO_CONNECT)
            elif email:
                user = User.objects.get(email=email, kind__in=[UserKind.EMPLOYER, UserKind.PRESCRIBER])
            else:
                raise User.DoesNotExist
            return HttpResponseRedirect(
                reverse(
                    "pro_connect:authorize",
                    query={"user_kind": user.kind, "next_url": new_url, "user_email": user.email},
                )
            )
        except User.DoesNotExist:
            return HttpResponseRedirect(reverse("signup:choose_user_kind", query={"next_url": new_url}))
