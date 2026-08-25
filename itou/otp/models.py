import logging
import secrets
import uuid

import xworkflows
from django.apps import apps
from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import make_password
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django_otp.models import Device, DeviceManager, ThrottlingMixin, TimestampMixin
from django_otp.plugins.otp_totp.models import (
    TOTPDevice as BaseTOTPDevice,
    default_key as generate_totp_key,
    key_validator,
)
from django_xworkflows import models as xwf_models
from encrypted_fields import EncryptedCharField

from itou.otp.emails import (
    notify_2fa_reset_request_accepted,
    notify_2fa_reset_request_denied,
    notify_2fa_reset_request_done,
)
from itou.otp.enums import ResetRequestState, ResetRequestTransition
from itou.utils.models import CopyModelFieldsMeta
from itou.utils.urls import get_absolute_url


logger = logging.getLogger(__name__)


class ItouDeviceManager(DeviceManager):
    def disable_for_user(self, user) -> int:
        now = timezone.now()
        devices = self.filter(user=user)
        for device in devices:
            device.disabled_at = now
        return self.bulk_update(devices, ["disabled_at"])


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
    disabled_at = models.DateTimeField(verbose_name="date de désactivation", null=True)

    objects = ItouDeviceManager()

    class Meta:
        verbose_name = "appareil d’authentification (TOTP)"
        verbose_name_plural = "appareils d’authentification (TOTP)"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"],
                name="unique_name_per_user",
                condition=models.Q(disabled_at=None),
            )
        ]

    @classmethod
    def from_persistent_id(cls, persistent_id, for_verify=False):
        from itou.otp.utils import load_placeholder_for_external_totp_device

        if placeholder := load_placeholder_for_external_totp_device(persistent_id):
            return placeholder
        return super().from_persistent_id(persistent_id, for_verify=for_verify)

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


class Itou2FAResetRequestWorkflow(xwf_models.Workflow):
    log_model = "otp.Itou2FAResetRequestTransitionLog"

    states = ResetRequestState.choices
    transitions = (
        (ResetRequestTransition.ACCEPT, ResetRequestState.PENDING, ResetRequestState.ACCEPTED),
        (ResetRequestTransition.RESEND, ResetRequestState.ACCEPTED, ResetRequestState.ACCEPTED),
        (
            ResetRequestTransition.DENY,
            [ResetRequestState.ACCEPTED, ResetRequestState.PENDING],
            ResetRequestState.DENIED,
        ),
        (ResetRequestTransition.RESET_DEVICES, ResetRequestState.ACCEPTED, ResetRequestState.DONE),
    )
    initial_state = ResetRequestState.PENDING


class Itou2FAResetRequestQuerySet(models.QuerySet):
    def deny(self, *, actor=None, msg=None):
        """Deny all Reset Request of this QuerySet."""
        for request in self:
            request.deny(actor=actor, msg=msg)


class Itou2FAResetRequest(xwf_models.WorkflowEnabled, models.Model):
    objects = Itou2FAResetRequestQuerySet.as_manager()

    class Meta:
        verbose_name = "Demande de réinitialisation 2FA"
        verbose_name_plural = "Demandes de réinitialisation 2FA"

    user = models.ForeignKey(
        getattr(settings, "AUTH_USER_MODEL", "auth.User"),
        verbose_name="utilisateur",
        help_text="L’utilisateur demandant la réinitialisation de ses 2FA.",
        related_name="itou_totp_reset_requests",
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField("Date de création", auto_now_add=True)
    updated_at = models.DateTimeField("Date de modification", auto_now=True)
    state = xwf_models.StateField(Itou2FAResetRequestWorkflow, verbose_name="état")
    nonce = models.CharField(default=secrets.token_hex, editable=False)

    def mark_used(self):
        self.used_at = timezone.now()
        self.save(update_fields=("used_at",))

    def __str__(self):
        return f"Demande de réinitialisation 2FA de {self.user.get_full_name()}"

    @xwf_models.transition()
    def accept(self, *, actor=None, msg=None):
        notify_2fa_reset_request_accepted(self)

    @xwf_models.transition()
    def deny(self, *, actor=None, msg=None):
        notify_2fa_reset_request_denied(self)

    @xwf_models.transition()
    def resend(self, *, actor=None, msg=None):
        notify_2fa_reset_request_accepted(self)

    @xwf_models.transition()
    def reset_devices(self, *, actor=None, msg=None) -> int:
        """Invalidates or deletes all 2FA user devices."""
        disabled = ItouTOTPDevice.objects.disable_for_user(self.user)
        deleted, _ = ItouStaticDevice.objects.filter(user=self.user).delete()
        notify_2fa_reset_request_done(self)
        return disabled + deleted

    @xworkflows.transition_check(ResetRequestTransition.RESET_DEVICES)
    def check_reset_devices(self):
        """Enforce reset link validity."""
        return self.updated_at + settings.OTP_RESET_LINK_VALIDITY > timezone.now()

    @xworkflows.transition_check(ResetRequestTransition.RESEND)
    def check_resend(self):
        """Enforce reset request validity."""
        return self.updated_at + settings.OTP_RESET_REQUEST_VALIDITY > timezone.now()

    @property
    def reset_link(self):
        return get_absolute_url(reverse("otp_views:reset_request_do_reset", args=(self.nonce,)))


class Itou2FAResetRequestTransitionLog(xwf_models.BaseTransitionLog):
    MODIFIED_OBJECT_FIELD = "reset_request"
    EXTRA_LOG_ATTRIBUTES = (("user", "actor", None),)

    reset_request = models.ForeignKey(Itou2FAResetRequest, related_name="logs", on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.RESTRICT,  # For traceability and accountability
        related_name="+",
    )
    msg = models.CharField("Message", null=True)

    class Meta:
        verbose_name = "log de demande de réinitialisation de 2FA"
        verbose_name_plural = "log des demandes de réinitialisation de 2FA"
