import factory.enums
import factory.fuzzy

from itou.audit_trail.models import AuditTrail, AuditTrailEventType
from tests.users.factories import ItouStaffFactory


class AuditTrailFactory(factory.django.DjangoModelFactory):
    """Generates AuditTrail() objects for unit tests."""

    event_type = factory.fuzzy.FuzzyChoice(AuditTrailEventType.values)
    user = factory.SubFactory(ItouStaffFactory)
    ip = "127.0.0.1"

    class Meta:
        model = AuditTrail
