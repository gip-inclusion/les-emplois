from django.contrib.auth.models import AnonymousUser
from rest_framework import authentication

from itou.api import models


class ServiceAccount(AnonymousUser):
    @property
    def is_authenticated(self):
        return True


class DepartmentTokenAuthentication(authentication.TokenAuthentication):
    model = models.DepartmentToken

    def authenticate_credentials(self, key):
        try:
            api_token = self.model.objects.get(key=key)
            return (ServiceAccount(), api_token)
        except self.model.DoesNotExist:
            # Do not raise AuthenticationFailed to allow other authentication to succeed
            return None
