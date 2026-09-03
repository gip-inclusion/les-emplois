from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditTrailEventType(models.TextChoices):
    CONNECTION = "CONNECTION", "Connexion"
    SECOND_FACTOR_RESET_REQUEST = "2FA_RESET_REQUEST", "Demande de réinitialisation du 2FA"


class AuditTrailManager(models.Manager):
    def cleanup(self):
        return self.filter(date__lt=timezone.now() - settings.AUDIT_TRAIL_STORAGE_DURATION).delete()

    def create(self, event_type: AuditTrailEventType, request, user=None, data: dict = None) -> None:
        """If user is not explicitly given, it's taken from request.user."""
        return super().create(
            event_type=event_type,
            user=user or request.user,
            ip=request.META.get("REMOTE_ADDR"),  # May not exist in request mocks
            browser_id=getattr(request, "browser_id", None),  # May not exist in request mocks
            data=data,
        )


class AuditTrail(models.Model):
    class Meta:
        indexes = (models.Index(fields=("date",)), models.Index(fields=("event_type", "user")))

    date = models.DateTimeField("date de l’évènement", auto_now_add=True)
    event_type = models.CharField("type de l’évènement", choices=AuditTrailEventType.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="utilisateur",
        related_name="+",
        null=True,
        on_delete=models.SET_NULL,
    )
    ip = models.GenericIPAddressField("adresse IP", null=True)
    browser_id = models.CharField("browser ID", null=True)
    data = models.JSONField("métadonnées", null=True)

    objects = AuditTrailManager()
