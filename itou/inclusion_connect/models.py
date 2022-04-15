import dataclasses

from django.db import models
from django.utils import timezone

from itou.users import enums as users_enums
from itou.users.models import User

from .constants import INCLUSION_CONNECT_STATE_EXPIRATION, PROVIDER_INCLUSION_CONNECT


class InclusionConnectQuerySet(models.QuerySet):
    def cleanup(self):
        expired_datetime = timezone.now() - INCLUSION_CONNECT_STATE_EXPIRATION
        return self.filter(created_at__lte=expired_datetime).delete()


class InclusionConnectState(models.Model):
    created_at = models.DateTimeField(default=timezone.now)
    # Length used in call to get_random_string()
    csrf = models.CharField(max_length=12, blank=False, null=False, unique=True)

    objects = models.Manager.from_queryset(InclusionConnectQuerySet)()


@dataclasses.dataclass
class InclusionConnectUserData:  # pylint: disable=too-many-instance-attributes
    username: str  # Provider ID
    first_name: str
    last_name: str
    email: str
    identity_provider: str = users_enums.IdentityProvider.INCLUSION_CONNECT


def userinfo_to_user_model_dict(userinfo: dict) -> dict:
    """
    Map User model attributes to provider's ones (USERINFO endpoint).
    """
    user_model_dict = {
        "username": userinfo["sub"],
        "first_name": userinfo["given_name"],
        "last_name": userinfo["family_name"],
        "email": userinfo["email"],
    }
    return user_model_dict


def create_user_from_ic_user_data(ic_user_data: InclusionConnectUserData):
    ic_user_data_dict = dataclasses.asdict(ic_user_data)  # Working with dicts is more readable.
    user = User(
        is_prescriber=True, **ic_user_data_dict
    )  # TODO: make this attribute dynamic to prepare SIAE's staff arrival.
    for key, value in ic_user_data_dict.items():
        # TODO: this method should be able to update every field.
        user.update_external_data_source_history_field(
            provider_name=PROVIDER_INCLUSION_CONNECT, field=key, value=value
        )
    return user


def update_user_from_ic_user_data(user: User, ic_user_data: InclusionConnectUserData):
    ic_user_data_dict = dataclasses.asdict(ic_user_data)
    for key, value in ic_user_data_dict.items():
        if value:
            setattr(user, key, value)
            user.update_external_data_source_history_field(
                provider_name=PROVIDER_INCLUSION_CONNECT, field=key, value=value
            )
    return user


def create_or_update_user(ic_user_data: InclusionConnectUserData):
    """
    Create a user using Inclusion Connect:
     - if there is already a user with this InclusionConnect ID, we return it.
     # TODO: username may not a good key as it's shared with FranceConnect and Django system.
     - if there is already a user with the email sent by InclusionConnect, we return this user
     - otherwise, we create a new user based on the data IC sent us.
    """
    # We can't use a get_or_create here because we have to set the provider data for each field.
    try:
        user = User.objects.get(username=ic_user_data.username)
        # Update user only if he was created from Inclusion Connect.
        update_user_from_ic_user_data(user, ic_user_data)
        created = False
    except User.DoesNotExist:
        try:
            user = User.objects.get(email=ic_user_data.email)
            # Don't update user if he already exists
            # but was not created by Inclusion Connect.
            created = False
        except User.DoesNotExist:
            user = create_user_from_ic_user_data(ic_user_data)
            created = True
    user.save()

    return user, created
