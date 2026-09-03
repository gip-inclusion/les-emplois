from django.apps import AppConfig


class AuditTrailConfig(AppConfig):
    name = "itou.audit_trail"

    def ready(self) -> None:
        from django.contrib.auth import user_logged_in

        import itou.audit_trail.receivers
        from itou.otp.signals import user_logged_in_with_2fa

        user_logged_in.connect(itou.audit_trail.receivers.on_user_logged_in)
        user_logged_in_with_2fa.connect(itou.audit_trail.receivers.on_user_logged_in_with_2fa)
