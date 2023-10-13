import dataclasses
from urllib.parse import unquote

from django.core import signing
from django.db import models
from django.utils import crypto, timezone

from itou.users.enums import IdentityProvider, UserKind
from itou.users.models import User

from .constants import OIDC_STATE_CLEANUP, OIDC_STATE_EXPIRATION


class InvalidKindException(Exception):
    def __init__(self, user, *args):
        self.user = user
        super().__init__(*args)


class MultipleUsersFoundException(Exception):
    def __init__(self, users, *args):
        self.users = users
        super().__init__(*args)


class OIDConnectQuerySet(models.QuerySet):
    def cleanup(self, at=None):
        at = at if at else timezone.now() - OIDC_STATE_CLEANUP
        return self.filter(created_at__lte=at).delete()


class OIDConnectState(models.Model):
    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now, db_index=True)
    used_at = models.DateTimeField(verbose_name="date d'utilisation", null=True)
    # Length used in call to get_random_string()
    state = models.CharField(max_length=12, unique=True)

    objects = OIDConnectQuerySet.as_manager()

    class Meta:
        abstract = True

    def __str__(self):
        return f"{self.state} created_at={self.created_at} used_at={self.used_at}"

    @classmethod
    def save_state(cls, **state):
        token = crypto.get_random_string(length=12)
        signer = signing.Signer()
        signed_token = signer.sign(token)
        cls.objects.create(state=token, **state)
        return signed_token

    @classmethod
    def get_from_state(cls, signed_state):
        # Cleanup old states if any.
        cls.objects.cleanup()

        if not signed_state:
            return None

        signer = signing.Signer()
        try:
            state = signer.unsign(unquote(signed_state))
        except signing.BadSignature:
            return None

        return cls.objects.filter(state=state).first()

    @property
    def expired_at(self):
        return self.created_at + OIDC_STATE_EXPIRATION

    def is_valid(self):
        # One-time use
        if self.used_at:
            return False
        self.used_at = timezone.now()
        self.save()

        return self.expired_at > timezone.now()


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
    kind: str
    login_allowed_user_kinds = [UserKind]

    def create_or_update_user(self, is_login=False):
        """
        Create or update a user managed by another identity provider.
         - If there is already a user with this username (user_info_dict["sub"])
           and from the same identity provider, we update and return it.
         - If there is already a user with the email, we return this user.
         - otherwise, we create a new user based on the data we received.
        """
        user_data_dict = dataclasses.asdict(self)
        user_data_dict = {key: value for key, value in user_data_dict.items() if value}
        try:
            # Look if a user with the given sub (username) exists for this identity_provider
            # We can't use a get_or_create here because we have to set the provider data for each field.
            user = User.objects.get(username=self.username, identity_provider=self.identity_provider)
            created = False
        except User.DoesNotExist:
            try:
                user = User.objects.get(email=self.email)
                created = False
                if user.identity_provider not in [IdentityProvider.DJANGO, self.identity_provider]:
                    # Don't update a user handled by another SSO provider.
                    return user, created
            except User.DoesNotExist:
                # User.objects.create_user does the following:
                # - set User.is_active to true,
                # - call User.set_unusable_password() if no password is given.
                # https://docs.djangoproject.com/fr/4.0/ref/contrib/auth/#django.contrib.auth.models.UserManager.create_user
                # NB: if we already have a user with the same username but with a different email and a different
                # provider the code will break here. We know it but since it's highly unlikely we just added a test
                # on this behaviour. No need to do a fancy bypass if it's never used.
                user = User.objects.create_user(**user_data_dict)
                created = True
        else:
            other_user = User.objects.exclude(pk=user.pk).filter(email=self.email).first()
            if other_user:
                # We found a user with its sub, but there's another user using its email.
                # This happens when the user tried to update its email with one already used by another account.
                raise MultipleUsersFoundException([user, other_user])

        if user.kind not in self.login_allowed_user_kinds or (user.kind != user_data_dict["kind"] and not is_login):
            raise InvalidKindException(user)

        if not created:
            for key, value in user_data_dict.items():
                # Don't update kind on login, it allows prescribers to log through employer form
                # which happens a lot...
                if is_login and key == "kind":
                    continue
                setattr(user, key, value)

        for key, value in user_data_dict.items():
            user.update_external_data_source_history_field(provider=self.identity_provider, field=key, value=value)
        user.save()
        return user, created

    @staticmethod
    def user_info_mapping_dict(user_info: dict):
        """
        Map Django's User class attributes to the identity provider ones.
        Override this method to add or change attributes.
        See https://openid.net/specs/openid-connect-core-1_0.html#StandardClaims
        """
        return {
            "username": user_info["sub"],
            "first_name": user_info["given_name"],
            "last_name": user_info["family_name"],
            "email": user_info["email"],
        }

    @classmethod
    def from_user_info(cls, user_info: dict):
        return cls(**cls.user_info_mapping_dict(user_info))
