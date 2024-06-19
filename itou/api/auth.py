from django.contrib.auth.models import AnonymousUser
from rest_framework import authentication

from . import models


class DepartmentTokenAuthentication(authentication.TokenAuthentication):
    model = models.DepartmentToken

    def authenticate_credentials(self, key):
        try:
            api_token = self.model.objects.get(key=key)
            return (AnonymousUser(), api_token)
        except self.model.DoesNotExist:
            # Do not raise AuthenticationFailed to allow other authentication to succeed
            return None
