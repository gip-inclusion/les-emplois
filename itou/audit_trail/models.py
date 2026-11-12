import datetime

from allauth.core.internal.httpkit import get_client_ip
from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditTrailEventType(models.TextChoices):
    PARTIAL_LOG_IN = "PARTIAL_LOG_IN", "L’utilisateur s’identifie (via un mot de passe ou un IDP)"
    LOG_IN = "LOG_IN", "L’utilisateur est connecté (2FA validé le cas échéant)"
    MFA_RESET_REQUEST = "MFA_RESET_REQUEST", "Demande de réinitialisation du 2FA"
    MFA_RESET = "MFA_RESET", "Réinitialisation du 2FA"


class AuditTrailManager(models.Manager):
    def cleanup(self):
        return self.filter(timestamp__lt=timezone.now() - settings.AUDIT_TRAIL_STORAGE_DURATION).delete()

    def log(self, event_type: AuditTrailEventType, request, user=None, data: dict | None = None) -> None:
        """If user is not explicitly given, it's taken from request.user."""
        return super().create(
            event_type=event_type,
            user=user or request.user,
            ip=get_client_ip(request),
            browser_id=getattr(request, "browser_id", None),  # May not exist in request mocks
            data=data,
        )


class AuditTrail(models.Model):
    class Meta:
        indexes = (models.Index(fields=("timestamp",)),)

    timestamp = models.DateTimeField("horodatage de l’évènement", auto_now_add=True)
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

    def _login_events(self):
        return AuditTrail.objects.filter(
            event_type=AuditTrailEventType.LOG_IN,
            user=self.user,
            timestamp__lt=self.timestamp - datetime.timedelta(days=1),
        ).order_by("timestamp")

    def credibility(self) -> float:
        """Measure the credibility of this event according to the past events.

        Gives a value between 0 (the event does not look legit
        according to past events), and 1 (the event looks legit).

        Consider >= 0.5 to be OK, < 0.5 to be suspicious.
        """
        trail = self._login_events()
        known_browser_ids = {event.browser_id for event in trail if event.browser_id}
        known_ips = {event.ip for event in trail}

        browser_is_known = self.browser_id in known_browser_ids
        ip_is_known = self.ip in known_ips
        if browser_is_known and ip_is_known:
            return 1
        if browser_is_known and not ip_is_known:
            return 0.9
        if ip_is_known and not browser_is_known:
            return 0.6
        return 0

    def credibility_explanation(self) -> list[str]:
        matching_ips = self._login_events().filter(ip=self.ip)
        matching_browser_ids = self._login_events().filter(browser_id=self.browser_id)
        explanation = []
        if len(matching_browser_ids) > 1:
            explanation.append(
                f"L’utilisateur s’est connecté {len(matching_browser_ids)} fois avec cet ordinateur, "
                f"du {matching_browser_ids.first().timestamp:%Y-%m-%d} au "
                f"{matching_browser_ids.last().timestamp:%Y-%m-%d}"
            )
        elif len(matching_browser_ids) == 1:
            explanation.append(
                f"L’utilisateur s’est connecté une seule fois avec cet ordinateur "
                f"le {matching_browser_ids.first().timestamp:%Y-%m-%d}"
            )
        else:
            explanation.append("L’utilisateur ne s’est jamais connecté avec cet ordinateur auparavant.")
        if len(matching_ips) > 1:
            explanation.append(
                f"L’utilisateur s’est connecté {len(matching_ips)} fois via ce réseau, "
                f"du {matching_ips.first().timestamp:%Y-%m-%d} au "
                f"{matching_ips.last().timestamp:%Y-%m-%d}"
            )
        elif len(matching_ips) == 1:
            explanation.append(
                f"L’utilisateur s’est connecté une seule fois via ce réseau, "
                f"le {matching_ips.first().timestamp:%Y-%m-%d}"
            )
        else:
            explanation.append("L’utilisateur n’avait jamais utilisé ce réseau auparavant.")

        return explanation

    @property
    def is_suspicious(self) -> bool:
        return self.credibility() < 0.5
