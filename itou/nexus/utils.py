from django.utils import timezone

from itou.nexus.enums import USER_KIND_MAPPING, Auth, Role, Service
from itou.nexus.models import NexusMembership, NexusRessourceSyncStatus, NexusStructure, NexusUser
from itou.users.enums import IdentityProvider
from itou.utils.urls import get_absolute_url


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


# ------------------------------------------------
# Sync utils


def init_full_sync(service):
    now = timezone.now()
    NexusRessourceSyncStatus.objects.update_or_create(
        service=service,
        defaults={"new_start_at": now},
        create_defaults={"service": service, "new_start_at": now},
    )
    return now


def complete_full_sync(service, started_at):
    return bool(
        NexusRessourceSyncStatus.objects.filter(service=service, new_start_at=started_at).update(
            new_start_at=None, valid_since=started_at
        )
    )


def serialize_user(user):
    # Serialize the user to reproduce the data received in the API
    return {
        "source_id": user.pk,
        "source_kind": user.kind,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "phone": user.phone,
        "last_login": user.last_login,
        "auth": {
            IdentityProvider.DJANGO: Auth.DJANGO,
            IdentityProvider.INCLUSION_CONNECT: Auth.INCLUSION_CONNECT,
            IdentityProvider.PRO_CONNECT: Auth.PRO_CONNECT,
        }[user.identity_provider],
    }


def build_user(user_data, service):
    return NexusUser(
        source=service,
        id=service_id(service, user_data["source_id"]),
        kind=USER_KIND_MAPPING[service][user_data["source_kind"]],
        **user_data,
    )


def sync_users(nexus_users, update_only=False):
    update_fields = [
        "kind",
        "source_kind",
        "source_id",
        "first_name",
        "last_name",
        "email",
        "phone",
        "last_login",
        "auth",
        "updated_at",
    ]
    if update_only:
        for nexus_user in nexus_users:
            nexus_user.updated_at = timezone.now()  # auto_now=True doesn't work with update/bulk_update
        return NexusUser.include_old.bulk_update(nexus_users, fields=update_fields)
    return len(
        NexusUser.objects.bulk_create(
            nexus_users,
            update_conflicts=True,
            update_fields=update_fields,
            unique_fields=["id"],
        )
    )


def serialize_membership(membership):
    # Serialize the user to reproduce the data received in the API
    structure = getattr(membership, "company", None) or membership.organization
    return {
        "user_id": membership.user_id,
        "structure_id": structure.uid,
        "role": Role.ADMINISTRATOR if membership.is_admin else Role.COLLABORATOR,
    }


def build_membership(membership_data, service):
    return NexusMembership(
        source=service,
        user_id=service_id(service, membership_data["user_id"]),
        structure_id=service_id(service, membership_data["structure_id"]),
        role=membership_data["role"],
    )


def sync_memberships(nexus_memberships):
    return len(
        NexusMembership.objects.bulk_create(
            nexus_memberships,
            update_conflicts=True,
            update_fields=["role", "updated_at"],
            unique_fields=["user", "structure"],
        )
    )


def serialize_structure(structure):
    # Serialize the user to reproduce the data received in the API
    name = getattr(structure, "display_name", None) or structure.name

    source_link = structure.get_card_url()
    if source_link:
        source_link = get_absolute_url(source_link)

    return {
        "source_id": structure.uid,
        "source_kind": structure.kind,
        "siret": structure.siret,
        "name": name,
        "phone": structure.phone,
        "email": structure.email,
        "address_line_1": structure.address_line_1,
        "address_line_2": structure.address_line_2,
        "post_code": structure.post_code,
        "city": structure.city,
        "department": structure.department,
        "website": structure.website,
        "opening_hours": "",
        "accessibility": "",
        "description": structure.description,
        "source_link": source_link or "",
    }


def build_structure(structure_data, service):
    return NexusStructure(
        source=service,
        id=service_id(service, structure_data["source_id"]),
        kind=structure_data["source_kind"],  # TODO: Add mapping
        **structure_data,
    )


def sync_structures(nexus_structures):
    return len(
        NexusStructure.objects.bulk_create(
            nexus_structures,
            update_conflicts=True,
            update_fields=[
                "kind",
                "source_kind",
                "source_id",
                "siret",
                "name",
                "phone",
                "email",
                "address_line_1",
                "address_line_2",
                "post_code",
                "city",
                "department",
                "accessibility",
                "description",
                "opening_hours",
                "source_link",
                "website",
                "updated_at",
            ],
            unique_fields=["id"],
        )
    )
