import logging

from django.utils import timezone

from itou.nexus.enums import STRUCTURE_KIND_MAPPING, USER_KIND_MAPPING, Auth, Role, Service
from itou.nexus.models import NexusMembership, NexusRessourceSyncStatus, NexusStructure, NexusUser
from itou.users.enums import IdentityProvider
from itou.utils.urls import get_absolute_url


logger = logging.getLogger(__name__)

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
        defaults={"in_progress_since": now},
        create_defaults={"service": service, "in_progress_since": now},
    )
    return now


def complete_full_sync(service, started_at):
    return bool(
        NexusRessourceSyncStatus.objects.filter(service=service, in_progress_since=started_at).update(
            in_progress_since=None, valid_since=started_at
        )
    )


USER_TRACKED_FIELDS = [
    "id",
    "kind",
    "first_name",
    "last_name",
    "email",
    "phone",
    "last_login",
    "identity_provider",
    "is_active",
]


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
    try:
        kind = USER_KIND_MAPPING[service][user_data["source_kind"]]
    except KeyError:
        kind = ""
        logger.exception("Invalid user kind=%s", user_data["source_kind"])

    return NexusUser(
        source=service,
        id=service_id(service, user_data["source_id"]),
        kind=kind,
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


MEMBERSHIP_TRACKED_FIELDS = [
    "user_id",
    "organization_id",
    "role",
    "is_active",
]


def serialize_membership(membership):
    # Serialize the membership to reproduce the data received in the API
    structure = getattr(membership, "company", None) or membership.organization
    return {
        "source_id": membership.nexus_id,
        "user_id": membership.user_id,
        "structure_id": structure.uid,
        "role": Role.ADMINISTRATOR if membership.is_admin else Role.COLLABORATOR,
    }


def build_membership(membership_data, service):
    return NexusMembership(
        source=service,
        id=service_id(service, membership_data["source_id"]),
        source_id=membership_data["source_id"],
        user_id=service_id(service, membership_data["user_id"]),
        structure_id=service_id(service, membership_data["structure_id"]),
        role=membership_data["role"],
    )


def sync_memberships(nexus_memberships):
    return len(
        NexusMembership.objects.bulk_create(
            nexus_memberships,
            update_conflicts=True,
            update_fields=["role", "updated_at", "user", "structure"],
            unique_fields=["id"],
        )
    )


PRESCRIBER_ORG_TRACKED_FIELDS = [
    "uid",
    "kind",
    "siret",
    "name",
    "phone",
    "email",
    "address_line_1",
    "address_line_2",
    "post_code",
    "city",
    "department",
    "website",
    "description",
]

COMPANY_TRACKED_FIELDS = PRESCRIBER_ORG_TRACKED_FIELDS + ["brand"]


def serialize_structure(structure):
    # Serialize the structure to reproduce the data received in the API
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
    try:
        kind = STRUCTURE_KIND_MAPPING[service][structure_data["source_kind"]]
    except KeyError:
        kind = ""
        logger.exception("Invalid structure kind=%s", structure_data["source_kind"])

    return NexusStructure(
        source=service,
        id=service_id(service, structure_data["source_id"]),
        kind=kind,
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


# Sync emplois data
def sync_emplois_users(users):
    emplois_users = [build_user(serialize_user(user), Service.EMPLOIS) for user in users]
    sync_users(emplois_users)
    pilotage_users = [build_user(serialize_user(user), Service.PILOTAGE) for user in users]
    monrecap_users = [build_user(serialize_user(user), Service.MON_RECAP) for user in users]
    sync_users(pilotage_users + monrecap_users, update_only=True)


def delete_emplois_users(users):
    NexusUser.include_old.filter(source_id__in=[user.pk for user in users], source__in=Service.local()).delete()


def sync_emplois_structures(structures):
    sync_structures([build_structure(serialize_structure(structure), Service.EMPLOIS) for structure in structures])


def delete_emplois_structure(structure):
    NexusStructure.include_old.filter(source_id=structure.uid, source=Service.EMPLOIS).delete()


def sync_emplois_memberships(memberships):
    sync_memberships(
        [build_membership(serialize_membership(membership), Service.EMPLOIS) for membership in memberships]
    )


def delete_emplois_memberships(memberships):
    NexusMembership.include_old.filter(
        source_id__in=[membership.nexus_id for membership in memberships], source=Service.EMPLOIS
    ).delete()
