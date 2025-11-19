import uuid

from django.utils import timezone

from itou.nexus.enums import Service
from itou.nexus.models import User


def activate_service(user, service):
    # Allow to track services without user sync mecanism
    assert service in [Service.PILOTAGE, Service.MON_RECAP]
    # pilotage uses (and is availableto ) users from les emplois
    # mon recap doesn't have user ids, just fake one
    id = uuid.uuid4() if service == Service.MON_RECAP else user.pk
    defaults = {
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone": user.phone,
        "last_login": user.last_login,
        "auth": "",
        "kind": "",
        "updated_at": timezone.now(),
    }
    User.objects.update_or_create(
        source=service,
        email=user.email,
        defaults=defaults,
        create_defaults=defaults
        | {
            "id": f"{service}--{id}",
            "source_id": id,
        },
    )
