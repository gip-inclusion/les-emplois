import dataclasses

from django.db import models
from django.utils import timezone

from itou.users.enums import IdentityProvider
from itou.users.models import User

from .constants import OIDC_STATE_EXPIRATION


class OIDConnectQuerySet(models.QuerySet):
    def cleanup(self):
        expired_datetime = timezone.now() - OIDC_STATE_EXPIRATION
        return self.filter(created_at__lte=expired_datetime).delete()


class OIDConnectState(models.Model):
    created_at = models.DateTimeField(default=timezone.now)
    # Length used in call to get_random_string()
    csrf = models.CharField(max_length=12, blank=False, null=False, unique=True)

    objects = models.Manager.from_queryset(OIDConnectQuerySet)()

    class Meta:
        abstract = True


@dataclasses.dataclass
class OIDConnectUserData:
    """
    Transforms data provided by the /userinfo endpoint into a Django-like User object.
    Note that this matches OpenID minimal claims (profile and email).
    FranceConnect and Inclusion Connect apps inherit from this class to match specific identity provider's logic.
    """

    email: str
    first_name: str
    last_name: str
    username: str
    identity_provider: IdentityProvider

    def create_django_user(self):
        user_data_dict = dataclasses.asdict(self)
        # User.objects.create_user does the following:
        # - set User.is_active to true,
        # - call User.set_unusable_password() if no password is given.
        # https://docs.djangoproject.com/fr/4.0/ref/contrib/auth/#django.contrib.auth.models.UserManager.create_user
        user = User.objects.create_user(**user_data_dict)
        for key, value in user_data_dict.items():
            user.update_external_data_source_history_field(
                provider_name=self.identity_provider.name, field=key, value=value
            )
        return user

    def update_django_user(self, user: User):
        user_data_dict = dataclasses.asdict(self)
        for key, value in user_data_dict.items():
            if value:
                setattr(user, key, value)
                user.update_external_data_source_history_field(
                    provider_name=self.identity_provider.name, field=key, value=value
                )
        user.save()
        return user

    def create_or_update_user(self):
        """
        Create or update a user managed by another identity provider.
         - If there is already a user with this username (user_info_dict["sub"]), we update and return it.
         - If there is already a user with the email, we return this user.
         - otherwise, we create a new user based on the data we received.
        """
        # We can't use a get_or_create here because we have to set the provider data for each field.
        try:
            user = User.objects.get(username=self.username)
            user = self.update_django_user(user=user)
            created = False
        except User.DoesNotExist:
            try:
                user = User.objects.get(email=self.email)
                created = False
            except User.DoesNotExist:
                user = self.create_django_user()
                created = True

        return user, created

    @classmethod
    def from_user_info_dict(cls, user_info_dict):
        """
        Map Django-User class attributes to the identity provider ones.
        """
        attrs = {
            "username": user_info_dict["sub"],
            "first_name": user_info_dict["given_name"],
            "last_name": user_info_dict["family_name"],
            "email": user_info_dict["email"],
        }
        return cls(**attrs)
