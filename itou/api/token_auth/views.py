from rest_framework import serializers
from rest_framework.authtoken import views as drf_authtoken_views
from rest_framework.authtoken.models import Token
from rest_framework.response import Response


TOKEN_ID_STR = "__token__"


class ObtainAuthToken(drf_authtoken_views.ObtainAuthToken):
    def post(self, request, *args, **kwargs):
        if request.data.get("username") == TOKEN_ID_STR:
            try:
                token = Token.objects.get(key=request.data.get("password"))
                return Response({"token": token.key})
            except Token.DoesNotExist:
                msg = "Impossible de se connecter avec le token fourni."
                raise serializers.ValidationError(msg, code="authorization")

        return super().post(request, *args, **kwargs)
