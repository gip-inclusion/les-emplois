import secrets
import uuid

from django.apps import apps
from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import make_password
from django.db import models
from django_otp.models import Device, ThrottlingMixin, TimestampMixin
from django_otp.plugins.otp_totp.models import (
    TOTPDevice as BaseTOTPDevice,
    default_key as generate_totp_key,
    key_validator,
)
from encrypted_fields import EncryptedCharField

from itou.utils.models import CopyModelFieldsMeta


# `django_otp.TOTPDevice` needs a few adjustments, but it's not an
# abstract model, so we cannot easily subclass it. Let's copy its
# fields and methods instead, and make a few additions and
# overrides.
class ItouTOTPDevice(
    TimestampMixin,
    ThrottlingMixin,
    Device,
    metaclass=CopyModelFieldsMeta,
    source_model=BaseTOTPDevice,
    copy_contents=True,
):
    # Override `id` to make it a UUID (non-enumerable).
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Override `key`, the base model stores it in clear text.
    key = EncryptedCharField(
        max_length=100,
        validators=[key_validator],
        default=generate_totp_key,
    )
    # Override `user` to get a proper "related_name".
    user = models.ForeignKey(
        getattr(settings, "AUTH_USER_MODEL", "auth.User"),
        help_text="L’utilisateur à qui appartient ce matériel.",
        related_name="itou_totp_devices",
        on_delete=models.CASCADE,
    )
    # FIXME (dbaty): add cronjob to purge disabled devices after 3 months
    disabled_at = models.DateTimeField(verbose_name="date de désactivation", null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"],
                name="unique_name_per_user",
                condition=models.Q(disabled_at=None),
            )
        ]

    # Override `Device._filter_persistent_id()` for our UUID primary key.
    # https://github.com/django-otp/django-otp/pull/29
    @classmethod
    def _filter_persistent_id(cls, persistent_id, for_verify=False):
        model_label, device_id = persistent_id.rsplit("/", 1)
        app_label, model_name = model_label.split(".")

        device_cls = apps.get_model(app_label, model_name)
        if issubclass(device_cls, Device):
            # -- patch starts here
            # device_set = device_cls.objects.filter(id=int(device_id))
            device_set = device_cls.objects.filter(pk=device_id)
            # -- end of patch
            if for_verify:
                device_set = device_set.select_for_update()
            return device_set
        return None


# A variant of django_otp's StaticDevice. We don't subclass it because
# it does not have any field and we're overriding its only method.
class ItouStaticDevice(TimestampMixin, ThrottlingMixin, Device):
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                name="unique_static_device_per_user",
            )
        ]

    def get_throttle_factor(self):
        # Copied from django_otp.StaticDevice.
        return getattr(settings, "OTP_STATIC_THROTTLE_FACTOR", 1)

    def verify_token(self, clear_code):
        # Adapted from django_otp.StaticDevice.
        # The only difference is that we must loop over each static
        # token to check if the stored (hashed) token corresponds.
        verify_allowed, _ = self.verify_is_allowed()
        if not verify_allowed:
            return False
        for token in self.static_tokens.all():
            if token.check_token(clear_code):
                token.delete()
                self.throttle_reset(commit=False)
                self.set_last_used_timestamp(commit=False)
                self.save()
                return True

        self.throttle_increment()
        return False


class ItouStaticTokenManager(models.Manager):
    def create(self, device):
        token_object = ItouStaticToken(device=device)
        clear_code = ItouStaticToken.generate_random_token()
        token_object.set_token(clear_code)
        token_object.save()
        return clear_code, token_object


class ItouStaticToken(models.Model):
    device = models.ForeignKey(
        ItouStaticDevice,
        related_name="static_tokens",
        on_delete=models.CASCADE,
    )
    hashed_code = models.CharField(max_length=255)

    objects = ItouStaticTokenManager()

    @staticmethod
    def generate_random_token():
        # Override base class to build a longer code than django_otp.
        # It looks like "ff6097b6_8aa11d87_019e0bc8".
        return "_".join(secrets.token_hex(4) for _ in range(3))

    def set_token(self, clear_code):
        self.hashed_code = make_password(clear_code)

    def check_token(self, clear_code):
        def setter(clear_code):
            self.set_token(clear_code)
            self.save(update_fields=["hashed_code"])

        return check_password(clear_code, self.hashed_code, setter)
