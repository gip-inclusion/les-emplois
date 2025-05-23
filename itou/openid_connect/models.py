import dataclasses
import logging
from typing import ClassVar
from urllib.parse import unquote

from django.core import signing
from django.db import models
from django.utils import crypto, timezone
from django.utils.html import format_html

from itou.openid_connect.constants import OIDC_STATE_CLEANUP, OIDC_STATE_EXPIRATION
from itou.users.enums import (
    IDENTITY_PROVIDER_SUPPORTED_USER_KIND,
    IdentityProvider,
    UserKind,
)
from itou.users.models import User
from itou.utils.constants import ITOU_HELP_CENTER_URL


logger = logging.getLogger(__name__)


class EmailInUseException(Exception):
    def __init__(self, user, *args):
        self.user = user
        super().__init__(*args)


class MultipleSubSameEmailException(Exception):
    def __init__(self, user, *args):
        self.user = user
        super().__init__(*args)

    def format_message_html(self, identity_provider):
        return format_html(
            "La connexion via {} a échoué car un compte existe déjà avec l’adresse email {}. "
            "Veuillez vous rapprocher du support pour débloquer la situation en suivant "
            "<a href='{}'>ce lien</a>.",
            identity_provider.label,
            self.user.email,
            ITOU_HELP_CENTER_URL,
        )


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
    kind: UserKind
    allowed_identity_provider_migration: ClassVar[tuple[IdentityProvider]] = ()
    allow_sub_update: ClassVar[bool] = False

    def is_sub_update_allowed(self, user):
        if user.is_staff:  # security check
            return False
        return user.allow_next_sso_sub_update or self.allow_sub_update

    @property
    def login_allowed_user_kinds(self) -> tuple[UserKind]:
        return IDENTITY_PROVIDER_SUPPORTED_USER_KIND[self.identity_provider]

    def check_valid_kind(self, user, user_data_dict, is_login):
        if user.kind not in self.login_allowed_user_kinds or (user.kind != user_data_dict["kind"] and not is_login):
            raise InvalidKindException(user)

    def create_or_update_user(self, is_login=False):
        """
        A user is being created or updated from information provided by an identity provider.
        A user is globally unique with the combination of SSO provider + sub (e.g. InclusionConnect:username).

        If we cannot find the user via provider + username:
         - If the email isn't in use, we'll create a new account.
         - If the email is being used by a provider in the allowed_identity_provider_migration configuration,
           we'll replace the account.
         - Otherwise, we'll raise an EmailInUseException (we do not support email overloading).
        """
        sso_data_dict = {k: v for k, v in dataclasses.asdict(self).items() if v}
        is_jobseeker = sso_data_dict["kind"] == UserKind.JOB_SEEKER
        jobseeker_fields = {"birthdate"}
        jobseeker_data_dict = {}
        user_data_dict = {}
        for field, value in sso_data_dict.items():
            if is_jobseeker and field in jobseeker_fields:
                jobseeker_data_dict[field] = value
            else:
                user_data_dict[field] = value

        created = False
        try:
            # Look if a user with the given sub (username) exists for this identity_provider
            # We can't use a get_or_create here because we have to set the provider data for each field.
            user = User.objects.get(username=self.username, identity_provider=self.identity_provider)
        except User.DoesNotExist:
            try:
                # A different user has already claimed this email address (we require emails to be unique)
                user = User.objects.get(email=self.email)
                if user.identity_provider == self.identity_provider:
                    if not self.is_sub_update_allowed(user):
                        raise MultipleSubSameEmailException(user)
                elif user.identity_provider not in self.allowed_identity_provider_migration:
                    self.check_valid_kind(user, user_data_dict, is_login)
                    raise EmailInUseException(user)
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

        self.check_valid_kind(user, user_data_dict, is_login)

        readonly_pii_fields = user.jobseeker_profile.readonly_pii_fields() if is_jobseeker else set()
        readonly_pii_fields_changed = []
        if not created:
            for key, value in user_data_dict.items():
                # Don't update kind on login, it allows prescribers to log through employer form
                # which happens a lot...
                if is_login and key == "kind":
                    continue
                if key in readonly_pii_fields:
                    if getattr(user, key) != value:
                        readonly_pii_fields_changed.append(key)
                else:
                    setattr(user, key, value)
        if jobseeker_data_dict:
            for key, value in jobseeker_data_dict.items():
                if key in readonly_pii_fields:
                    if getattr(user.jobseeker_profile, key) != value:
                        readonly_pii_fields_changed.append(key)
                else:
                    setattr(user.jobseeker_profile, key, value)
            user.jobseeker_profile.save(update_fields=jobseeker_data_dict)
        if readonly_pii_fields_changed:
            logger.warning(
                "Not updating fields %s on job seeker pk=%d because their identity has been certified.",
                ", ".join(sorted(readonly_pii_fields_changed)),
                user.pk,
            )

        for key, value in user_data_dict.items():
            user.update_external_data_source_history_field(provider=self.identity_provider, field=key, value=value)

        user.allow_next_sso_sub_update = False  # Always disable this at login, even if the sub wasn't changed
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
