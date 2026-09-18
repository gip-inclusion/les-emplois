from dataclasses import dataclass, field, replace

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.signing import BadSignature
from django.urls import reverse

from itou.companies.models import Company, CompanyMembership
from itou.insertion.models import Structure
from itou.nexus.enums import STRUCTURE_KIND_MAPPING, NexusStructureKind, NexusUserKind, Service
from itou.nexus.models import NexusMembership, NexusUser
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
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
    latitude: float | None
    longitude: float | None
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

    @property
    def has_contact_form(self):
        return bool(self.email)


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


def _native_kind(obj):
    return STRUCTURE_KIND_MAPPING[Service.EMPLOIS].get(obj.kind, "")


def _kind_label(kind, obj=None):
    if kind:
        return NexusStructureKind(kind).label
    if obj is not None:
        return obj.get_kind_display()
    return ""


def _native_organization(obj, distance):
    kind = _native_kind(obj)
    return DirectoryOrganization(
        key=f"{obj._meta.label_lower}-{obj.pk}",
        name=obj.display_name if isinstance(obj, Company) else obj.name,
        kind=kind,
        kind_label=_kind_label(kind, obj),
        address=_address(obj),
        phone=obj.phone,
        email=obj.email,
        website=obj.website,
        card_url=obj.get_card_url(),
        distance=_as_km(distance),
        latitude=obj.latitude,
        longitude=obj.longitude,
        siret=obj.siret or "",
    )


def _nexus_organization(structure, native, distance):
    if native:
        return replace(
            _native_organization(native, distance),
            key=structure.id,
            siret=native.siret or structure.siret or "",
        )

    return DirectoryOrganization(
        key=structure.id,
        name=structure.name,
        kind=structure.kind,
        kind_label=_kind_label(structure.kind),
        address=_address(structure),
        phone=structure.phone,
        email=structure.email,
        website=structure.website,
        card_url=structure.source_link or None,
        distance=_as_km(distance),
        latitude=structure.latitude,
        longitude=structure.longitude,
        siret=structure.siret or "",
    )


def _dora_organization(structure, dora_structure, distance):
    if not dora_structure:
        return _nexus_organization(structure, None, distance)
    return DirectoryOrganization(
        key=structure.id,
        name=dora_structure.name,
        kind=structure.kind,
        kind_label=_kind_label(structure.kind),
        address=_address(dora_structure),
        phone=dora_structure.phone,
        email=dora_structure.email,
        website=dora_structure.website,
        card_url=reverse("insertion_views:structure_card", kwargs={"structure_uid": dora_structure.uid}),
        distance=_as_km(distance),
        latitude=dora_structure.coordinates.y if dora_structure.coordinates else None,
        longitude=dora_structure.coordinates.x if dora_structure.coordinates else None,
        siret=dora_structure.siret or structure.siret or "",
    )


def _dedupe_organizations(organizations):
    by_identity = {}
    for organization in organizations:
        identity = organization.siret or organization.key
        current = by_identity.get(identity)
        if current is None or (organization.distance, not organization.card_url, organization.name) < (
            current.distance,
            not current.card_url,
            current.name,
        ):
            by_identity[identity] = organization
    return sorted(by_identity.values(), key=lambda organization: (organization.distance, organization.name))


def _unique_by_siret(objects):
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
    if not str(recipient_id).startswith("user-"):
        person.recipient_id = recipient_id
    if not person.phone:
        person.phone = user.phone
    if kind == NexusUserKind.GUIDE:
        person.kind = kind
    if organization.key not in {item.key for item in person.organizations}:
        person.organizations.append(organization)


def _nearby_memberships(model, organization_field, users, origin):
    coords_field = f"{organization_field}__coords"
    return (
        model.objects.filter(
            user__in=users,
            **{f"{coords_field}__dwithin": (origin, D(km=DIRECTORY_RADIUS_KM))},
        )
        .select_related("user", organization_field)
        .annotate(directory_distance=Distance(coords_field, origin) / 1000)
    )


def get_directory_people(origin, *, email=None):
    people = {}
    local_users = User.objects.filter(kind=UserKind.PROFESSIONAL, is_directory_opted_out=False)
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

    nexus_memberships = NexusMembership.objects.filter(
        structure__coords__dwithin=(origin, D(km=DIRECTORY_RADIUS_KM))
    ).select_related("user", "structure")
    if email:
        nexus_memberships = nexus_memberships.filter(user__email__iexact=email)
    nexus_memberships = list(
        nexus_memberships.annotate(directory_distance=Distance("structure__coords", origin) / 1000)
    )

    siret_values = {membership.structure.siret for membership in nexus_memberships if membership.structure.siret}
    companies = _unique_by_siret(Company.objects.filter(siret__in=siret_values))
    prescribers = _unique_by_siret(PrescriberOrganization.objects.filter(siret__in=siret_values))
    dora_source_ids = {
        membership.structure.source_id
        for membership in nexus_memberships
        if membership.structure.source == Service.DORA
    }
    dora_candidates = list(
        Structure.objects.filter(siret__in=siret_values, coordinates__isnull=False)
        | Structure.objects.filter(uid__in=dora_source_ids, coordinates__isnull=False)
    )
    dora_structures_by_uid = {obj.uid: obj for obj in dora_candidates}
    dora_structures_by_siret = _unique_by_siret(obj for obj in dora_candidates if obj.siret)
    opted_out_emails = {
        item.casefold()
        for item in User.objects.filter(
            is_directory_opted_out=True,
            email__in={membership.user.email for membership in nexus_memberships},
        ).values_list("email", flat=True)
    }

    for membership in nexus_memberships:
        user = membership.user
        if user.email.casefold() in opted_out_emails:
            continue
        structure = membership.structure
        if structure.source == Service.DORA:
            organization = _dora_organization(
                structure,
                dora_structures_by_uid.get(structure.source_id) or dora_structures_by_siret.get(structure.siret),
                membership.directory_distance,
            )
        else:
            native = companies.get(structure.siret) or prescribers.get(structure.siret)
            organization = _nexus_organization(structure, native, membership.directory_distance)
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
        (person for person in people.values() if person.organizations),
        key=lambda person: (person.last_name, person.first_name, person.email),
    )


def get_directory_person(origin, key):
    identifier = get_person_identifier(key)
    email = _get_person_email(identifier)
    if not email:
        return None
    return next(iter(get_directory_people(origin, email=email)), None)
