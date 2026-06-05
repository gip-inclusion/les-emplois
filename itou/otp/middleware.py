import django_otp.middleware

from itou.otp.models import ItouTOTPDevice


class OtpMiddleware(django_otp.middleware.OTPMiddleware):
    # Override base class, that uses the `Device` class. See
    # `ItouTOTPDevice.from_persistent_id()` for the reason why we need
    # to override that in our own model.
    def _device_from_persistent_id(self, persistent_id: str):
        persistent_id = self._normalize_persistent_id(persistent_id)
        return ItouTOTPDevice.from_persistent_id(persistent_id)
