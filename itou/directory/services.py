from dataclasses import dataclass, field

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.signing import BadSignature
from django.urls import reverse

from itou.companies.models import Company, CompanyMembership
from itou.directory.models import DirectoryProfile
from itou.insertion.models import Structure
from itou.nexus.enums import STRUCTURE_KIND_MAPPING, NexusStructureKind, NexusUserKind, Service
from itou.nexus.models import NexusMembership, NexusUser
from itou.prescribers.models import PrescriberMembership
from itou.users.enums import UserKind
from itou.users.models import User


DIRECTORY_RADIUS_KM = 20
PERSON_KEY_SALT = "directory-person"


@dataclass(frozen=True)
class DirectoryOrganization:
    key: str
    name: str
    kind: str
    kind_label: str
    address: str
    phone: str
    email: str
    website: str
    card_url: str | None
    distance: float
    siret: str = ""


@dataclass
class DirectoryPerson:
    recipient_id: str
    first_name: str
    last_name: str
    email: str
    phone: str
    kind: str
    organizations: list[DirectoryOrganization] = field(default_factory=list)

    @property
    def key(self):
        return signing.dumps(self.recipient_id, salt=PERSON_KEY_SALT)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def kind_label(self):
        return NexusUserKind(self.kind).label if self.kind else ""

    @property
    def main_organization(self):
        return self.organizations[0]

    @property
    def other_organizations_count(self):
        return max(len(self.organizations) - 1, 0)


def get_person_identifier(key):
    try:
        return signing.loads(key, salt=PERSON_KEY_SALT)
    except BadSignature as exc:
        raise ValueError("Invalid person key") from exc


def _get_person_email(identifier):
    if str(identifier).startswith("user-"):
        public_id = str(identifier).removeprefix("user-")
        try:
            return User.objects.filter(public_id=public_id).values_list("email", flat=True).first()
        except (ValidationError, ValueError):
            return None
    return NexusUser.objects.filter(pk=identifier).values_list("email", flat=True).first()


def _as_km(distance):
    return float(getattr(distance, "km", distance))


def _address(obj):
    return " ".join(part for part in [obj.address_line_1, obj.address_line_2, obj.post_code, obj.city] if part)


def _native_organization(obj, distance):
    kind = STRUCTURE_KIND_MAPPING[Service.EMPLOIS].get(obj.kind, "")
    return DirectoryOrganization(
        key=f"{obj._meta.label_lower}-{obj.pk}",
        name=obj.display_name if isinstance(obj, Company) else obj.name,
        kind=kind,
        kind_label=NexusStructureKind(kind).label if kind else obj.get_kind_display(),
        address=_address(obj),
        phone=obj.phone,
        email=obj.email,
        website=obj.website,
        card_url=obj.get_card_url(),
        distance=_as_km(distance),
        siret=obj.siret or "",
    )


def _nexus_organization(structure, dora_structure, distance):
    # Prefer the local DORA card when this Nexus structure has one.
    obj = dora_structure or structure
    card_url = (
        reverse("insertion_views:structure_card", kwargs={"structure_uid": dora_structure.uid})
        if dora_structure
        else structure.source_link or None
    )
    return DirectoryOrganization(
        key=structure.id,
        name=obj.name,
        kind=structure.kind,
        kind_label=NexusStructureKind(structure.kind).label if structure.kind else "",
        address=_address(obj),
        phone=obj.phone,
        email=obj.email,
        website=obj.website,
        card_url=card_url,
        distance=_as_km(distance),
        siret=structure.siret or "",
    )


def _dedupe_organizations(organizations):
    # Keep the nearest occurrence of each structure; input order breaks ties in distance and name.
    by_identity = {}
    for organization in sorted(organizations, key=lambda item: (item.distance, item.name)):
        by_identity.setdefault(organization.siret or organization.key, organization)
    return list(by_identity.values())


def _unique_by_siret(objects):
    """Only link a local DORA sheet when its SIRET identifies a single structure."""
    by_siret = {}
    ambiguous_sirets = set()
    for obj in objects:
        if obj.siret in ambiguous_sirets:
            continue
        if obj.siret in by_siret:
            by_siret.pop(obj.siret)
            ambiguous_sirets.add(obj.siret)
        else:
            by_siret[obj.siret] = obj
    return by_siret


def _add_person(people, user, organization, *, recipient_id, kind):
    person = people.setdefault(
        user.email.casefold(),
        DirectoryPerson(
            recipient_id=recipient_id,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            phone=user.phone,
            kind=kind,
        ),
    )
    person.organizations.append(organization)


def _nearby_memberships(model, organization_field, users, origin):
    # Company and prescriber memberships name their organization field differently.
    coords_field = f"{organization_field}__coords"
    return (
        model.objects.filter(
            user__in=users,
            **{f"{coords_field}__dwithin": (origin, D(km=DIRECTORY_RADIUS_KM))},
        )
        .select_related("user", organization_field)
        .order_by("pk")
        .annotate(directory_distance=Distance(coords_field, origin) / 1000)
    )


def get_directory_people(origin, *, email=None):
    """Build one card per email from local professionals, then Nexus memberships.

    The first profile wins as a whole: local data takes precedence over Nexus.
    Other occurrences contribute organizations only, without merging profile fields.
    """
    people = {}
    local_users = User.objects.filter(kind=UserKind.PROFESSIONAL).exclude(directory_profile__is_opted_out=True)
    if email:
        local_users = local_users.filter(email__iexact=email)

    for model, organization_field in (
        (CompanyMembership, "company"),
        (PrescriberMembership, "organization"),
    ):
        for membership in _nearby_memberships(model, organization_field, local_users, origin):
            user = membership.user
            _add_person(
                people,
                user,
                _native_organization(membership.get_organization(), membership.directory_distance),
                recipient_id=f"user-{user.public_id}",
                kind=NexusUserKind.FACILITY_MANAGER,
            )

    nexus_memberships = (
        NexusMembership.objects.filter(structure__coords__dwithin=(origin, D(km=DIRECTORY_RADIUS_KM)))
        .select_related("user", "structure")
        .order_by("pk")
    )
    if email:
        nexus_memberships = nexus_memberships.filter(user__email__iexact=email)
    nexus_memberships = list(
        nexus_memberships.annotate(directory_distance=Distance("structure__coords", origin) / 1000)
    )

    # Nexus and local DORA structures are stored separately; link them by SIRET.
    dora_sirets = {
        membership.structure.siret
        for membership in nexus_memberships
        if membership.structure.source == Service.DORA and membership.structure.siret
    }
    dora_structures = _unique_by_siret(Structure.objects.filter(siret__in=dora_sirets))
    # A local user who opted out may also have a Nexus profile with the same email.
    opted_out_emails = {
        item.casefold()
        for item in DirectoryProfile.objects.filter(
            is_opted_out=True,
            user__email__in={membership.user.email for membership in nexus_memberships},
        ).values_list("user__email", flat=True)
    }

    for membership in nexus_memberships:
        user = membership.user
        if user.email.casefold() in opted_out_emails:
            continue
        structure = membership.structure
        organization = _nexus_organization(
            structure,
            dora_structures.get(structure.siret) if structure.source == Service.DORA else None,
            membership.directory_distance,
        )
        _add_person(
            people,
            user,
            organization,
            recipient_id=user.id,
            kind=user.kind,
        )

    for person in people.values():
        person.organizations = _dedupe_organizations(person.organizations)
    return sorted(
        people.values(),
        key=lambda person: (person.last_name, person.first_name, person.email),
    )


def get_directory_person(origin, key):
    identifier = get_person_identifier(key)
    email = _get_person_email(identifier)
    if not email:
        return None
    # Rebuild the card for this origin so it still respects distance and opt-outs.
    return next(iter(get_directory_people(origin, email=email)), None)
