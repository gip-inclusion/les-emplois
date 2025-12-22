from itou.nexus.enums import Service
from itou.nexus.models import NexusUser


SERVICE_MAPPING = {
    Service.COMMUNAUTE: "la-communauté",
    Service.DORA: "dora",
    Service.EMPLOIS: "emplois-de-linclusion",
    Service.MARCHE: "le-marché",
    Service.DATA_INCLUSION: "data-inclusion",
    Service.PILOTAGE: "pilotage",
    Service.MON_RECAP: "mon-recap",
}


def service_id(service, id):
    return f"{SERVICE_MAPPING[service]}--{id}"


def activate_service(user, service):
    # Allow to track services without user sync mechanism
    assert service in [Service.PILOTAGE, Service.MON_RECAP]
    defaults = {
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone": user.phone,
        "last_login": user.last_login,
        "auth": "",
        "kind": "",
    }
    NexusUser.objects.update_or_create(
        source=service,
        email=user.email,
        defaults=defaults,
        create_defaults=defaults
        | {
            "id": service_id(service, user.pk),
            "source_id": user.pk,
        },
    )
