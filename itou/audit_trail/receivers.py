from itou.audit_trail.models import AuditTrail, AuditTrailEventType


def on_user_logged_in(sender, request, user, **kwargs):
    AuditTrail.objects.create(AuditTrailEventType.CONNECTION, request, user=user)
