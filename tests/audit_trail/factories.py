from dataclasses import dataclass

import factory.enums
import factory.fuzzy

from itou.audit_trail.models import AuditTrail, AuditTrailEventType
from itou.users.models import User
from tests.users.factories import ItouStaffFactory


@dataclass
class Request:
    user: User
    META: dict
    browser_id: str


class RequestFactory(factory.Factory):
    user = factory.SubFactory(ItouStaffFactory)
    META = {"REMOTE_ADDR": "127.0.0.1"}
    browser_id = "random"

    class Meta:
        strategy = factory.enums.BUILD_STRATEGY
        model = Request


class AuditTrailFactory(factory.django.DjangoModelFactory):
    """Generates AuditTrail() objects for unit tests."""

    event_type = factory.fuzzy.FuzzyChoice(AuditTrailEventType.values)
    request = factory.SubFactory(RequestFactory)

    class Meta:
        model = AuditTrail
