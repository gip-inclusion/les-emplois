import logging

from rest_framework import serializers
from rest_framework.authtoken import views as drf_authtoken_views
from rest_framework.authtoken.models import Token
from rest_framework.response import Response


logger = logging.getLogger(__name__)


TOKEN_ID_STR = "__token__"


class ObtainAuthToken(drf_authtoken_views.ObtainAuthToken):
    def post(self, request, *args, **kwargs):
        if request.data.get("username") == TOKEN_ID_STR:
            password = request.data.get("password")
            try:
                token = Token.objects.get(key=password)
                return Response({"token": token.key})
            except Token.DoesNotExist:
                logger.info(
                    "Auth with special user '%s' failed: unknown token received (len=%s)",
                    TOKEN_ID_STR,
                    len(password) if password is not None else None,
                )
                raise serializers.ValidationError(
                    "Impossible de se connecter avec le token fourni.", code="authorization"
                )

        return super().post(request, *args, **kwargs)
