import dataclasses

from django.db import models
from django.utils import timezone

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
class OIDConnectUserData:  # openid profile and email claims
    """
    Data provided by the /userinfo endpoint.
    """

    username: str
    first_name: str
    last_name: str
    email: str

    def create_user_from_user_data(self):
        # Parent dataclasses can't have default values because of the way Python handles dataclass inheritance.
        # See https://stackoverflow.com/a/53085935/3086625
        # Make sure the child class specified an identity provider.
        provider = getattr(self, "identity_provider")
        if not provider:
            raise NotImplementedError

        user_data_dict = dataclasses.asdict(self)
        # User.objects.create_user does the following:
        # - set User.is_active to true,
        # - call User.set_unusable_password() if no password is given.
        # See https://docs.djangoproject.com/fr/4.0/ref/contrib/auth/#django.contrib.auth.models.UserManager.create_user
        # TODO: refactor with signup forms.
        user = User.objects.create_user(**user_data_dict)
        for key, value in user_data_dict.items():
            # TODO: this method should be able to update every field.
            user.update_external_data_source_history_field(provider_name=provider.name, field=key, value=value)
        return user

    def update_user_from_user_data(self, user: User):
        provider = getattr(self, "identity_provider")
        if not provider:
            raise NotImplementedError

        user_data_dict = dataclasses.asdict(self)
        for key, value in user_data_dict.items():
            if value:
                setattr(user, key, value)
                user.update_external_data_source_history_field(provider_name=provider.name, field=key, value=value)
        user.save()
        return user

    def create_or_update_user(self):
        """
        Create a user using Inclusion Connect:
         - if there is already a user with this InclusionConnect ID, we return it.
         - if there is already a user with the email sent by InclusionConnect, we return this user
         - otherwise, we create a new user based on the data IC sent us.
        """
        # We can't use a get_or_create here because we have to set the provider data for each field.
        try:
            user = User.objects.get(username=self.username)
            # Update user only if he was created from Inclusion Connect.
            user = self.update_user_from_user_data(user=user)
            created = False
        except User.DoesNotExist:
            try:
                user = User.objects.get(email=self.email)
                # Don't update user if he already exists
                # but was not created by Inclusion Connect.
                created = False
            except User.DoesNotExist:
                user = self.create_user_from_user_data()
                created = True

        return user, created

    @classmethod
    def from_user_info_dict(cls, user_info_dict):
        attrs = {
            "username": user_info_dict["sub"],
            "first_name": user_info_dict["given_name"],
            "last_name": user_info_dict["family_name"],
            "email": user_info_dict["email"],
        }
        return cls(**attrs)
