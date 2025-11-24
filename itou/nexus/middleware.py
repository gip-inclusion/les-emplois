import logging

from django.contrib.auth import logout
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.deprecation import MiddlewareMixin

from itou.nexus.utils import decode_jwt
from itou.users.enums import UserKind
from itou.users.models import User


logger = logging.getLogger(__name__)


class AutoLoginMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if "auto_login" not in request.GET:
            return

        query_params = request.GET.copy()
        auto_login = query_params.pop("auto_login")
        email = None

        new_url = f"{request.path}?{query_params.urlencode()}" if query_params else request.path

        if len(auto_login) != 1:
            logger.info("Nexus auto login: Multiple tokens found -> ignored")
            return HttpResponseRedirect(new_url)
        else:
            [token] = auto_login

        try:
            decoded_data = decode_jwt(token)
            email = decoded_data.get("email")
        except ValueError:
            logger.info("Invalid auto login token")

        if email is None:
            logger.info("Nexus auto login: Missing email in token -> ignored")
            return HttpResponseRedirect(new_url)

        if request.user.is_authenticated:
            if request.user.email == email:
                logger.info("Nexus auto login: user is already logged in")
                return HttpResponseRedirect(new_url)
            else:
                logger.info("Nexus auto login: wrong user is logged in -> logging them out")
                # We should probably also logout the user from ProConnect but it requires to redirect to ProConnect
                # and the flow becomes a lotmore complicated
                logout(request)

        try:
            user = User.objects.get(email=email, kind__in=[UserKind.EMPLOYER, UserKind.PRESCRIBER])
            logger.info("Nexus auto login: %s was found and forwarded to ProConnect", user)
            return HttpResponseRedirect(
                reverse(
                    "pro_connect:authorize",
                    query={"user_kind": user.kind, "next_url": new_url, "user_email": user.email},
                )
            )
        except User.DoesNotExist:
            # There's no user with this email, we have to create them an account but we need to know
            # if they are a prescriber or an employer.
            logger.info("Nexus auto login: no user found for jwt=%s", token)
            return HttpResponseRedirect(reverse("signup:choose_user_kind", query={"next_url": new_url}))
