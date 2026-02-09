from django.utils import timezone

from itou.nexus.enums import STRUCTURE_KIND_MAPPING, USER_KIND_MAPPING, Auth, Service
from itou.nexus.models import ActivatedService, NexusMembership, NexusRessourceSyncStatus, NexusStructure, NexusUser
from itou.users.enums import IdentityProvider


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


def sync_users(nexus_users):
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
    return len(
        NexusUser.objects.bulk_create(
            nexus_users,
            update_conflicts=True,
            update_fields=update_fields,
            unique_fields=["id"],
        )
    )


def build_membership(membership_data, service):
    return NexusMembership(
        id=service_id(service, membership_data["source_id"]),
        source_id=membership_data["source_id"],
        source=service,
        user_id=service_id(service, membership_data["user_id"]),
        structure_id=service_id(service, membership_data["structure_id"]),
        role=membership_data["role"],
    )


def sync_memberships(nexus_memberships):
    user_pks = [membership.user_id for membership in nexus_memberships]
    structure_pks = [membership.structure_id for membership in nexus_memberships]
    existing_user_pks = set(NexusUser.objects.filter(pk__in=user_pks).values_list("pk", flat=True))
    existing_structure_pks = set(NexusStructure.objects.filter(pk__in=structure_pks).values_list("pk", flat=True))
    filtered_memberships = filter(
        lambda membership: (
            membership.user_id in existing_user_pks and membership.structure_id in existing_structure_pks
        ),
        nexus_memberships,
    )
    return len(
        NexusMembership.objects.bulk_create(
            filtered_memberships,
            update_conflicts=True,
            update_fields=["role", "updated_at", "user", "structure"],
            unique_fields=["id"],
        )
    )


def build_structure(structure_data, service):
    return NexusStructure(
        source=service,
        id=service_id(service, structure_data["source_id"]),
        kind=STRUCTURE_KIND_MAPPING[service][structure_data["source_kind"]],
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


# Activate pilotage
def activate_pilotage(user):
    ActivatedService.objects.activate(user=user, service=Service.PILOTAGE)
