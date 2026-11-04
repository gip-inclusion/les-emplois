import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from email.utils import formataddr

from django.conf import settings
from django.contrib import messages
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from itoutils.urls import add_url_params

from itou.api.throttling import FailSafeUserRateThrottle
from itou.companies.models import Company, CompanyMembership
from itou.directory.enums import ContactSubject
from itou.directory.models import ContactMessage, DirectoryProfile
from itou.emails.utils import get_email_message
from itou.insertion.models import Structure
from itou.nexus.enums import STRUCTURE_KIND_MAPPING, NexusStructureKind, NexusUserKind, Service
from itou.nexus.models import NexusMembership
from itou.prescribers.models import PrescriberMembership
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.auth import check_request
from itou.utils.pagination import pager
from itou.utils.readonly import http_methods, readonly_view
from itou.utils.urls import get_safe_url
from itou.www.directory_views.forms import ContactMessageForm, PeopleSearchForm
from itou.www.directory_views.perms import can_access_directory


MESSAGE_RATE_LIMIT = 50
MESSAGE_RATE_LIMIT_PERIOD = int(timedelta(days=1).total_seconds())


DIRECTORY_RADIUS_KM = 20


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
    public_id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    phone: str
    kind: str
    organizations: list[DirectoryOrganization] = field(default_factory=list)

    @property
    def full_name(self):
        # Follows User.get_inverted_full_name().
        return f"{self.last_name.upper()} {self.first_name.strip().title()}".strip()

    @property
    def kind_label(self):
        return NexusUserKind(self.kind).label if self.kind else ""

    @property
    def main_organization(self):
        # Populated by get_directory_people, do not access before the directory
        # is fully constructed.
        return self.organizations[0]

    @property
    def other_organizations_count(self):
        return max(len(self.organizations) - 1, 0)


def _as_km(distance):
    return float(getattr(distance, "km", distance))


def _native_organization(obj, distance):
    kind = STRUCTURE_KIND_MAPPING[Service.EMPLOIS].get(obj.kind, "")
    return DirectoryOrganization(
        key=f"{obj._meta.label_lower}-{obj.pk}",
        name=obj.display_name if isinstance(obj, Company) else obj.name,
        kind=kind,
        kind_label=NexusStructureKind(kind).label if kind else obj.get_kind_display(),
        address=obj.address_on_one_line,
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
        address=obj.address_on_one_line,
        phone=obj.phone,
        email=obj.email,
        website=obj.website,
        card_url=card_url,
        distance=_as_km(distance),
        siret=structure.siret or "",
    )


def _order_and_dedupe_organizations(organizations):
    # Keep the nearest occurrence of each structure; input order breaks ties in distance and name.
    by_identity = {}
    for organization in sorted(organizations, key=lambda item: (item.distance, item.name, item.key)):
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


def _add_person(people, user, organization, *, kind):
    person = people.setdefault(
        user.email.casefold(),
        DirectoryPerson(
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            phone=user.phone,
            kind=kind,
            public_id=user.public_id,
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


def get_directory_people(origin, *, public_id=None):
    """Build one card per email from local professionals, then Nexus memberships.

    The first profile wins as a whole: local data takes precedence over Nexus.
    Other occurrences contribute organizations only, without merging profile fields.
    """
    people = {}
    local_users = User.objects.filter(kind=UserKind.PROFESSIONAL).exclude(directory_profile__is_opted_out=True)
    if public_id:
        local_users = local_users.filter(public_id=public_id)

    for model, organization_field, user_kind in (
        (CompanyMembership, "company", NexusUserKind.FACILITY_MANAGER),
        (PrescriberMembership, "organization", NexusUserKind.GUIDE),
    ):
        for membership in _nearby_memberships(model, organization_field, local_users, origin):
            user = membership.user
            _add_person(
                people,
                user,
                _native_organization(membership.get_organization(), membership.directory_distance),
                kind=user_kind,
            )

    nexus_memberships = (
        NexusMembership.objects.filter(structure__coords__dwithin=(origin, D(km=DIRECTORY_RADIUS_KM)))
        .select_related("user", "structure")
        .order_by("pk")
    )
    if public_id:
        nexus_memberships = nexus_memberships.filter(user__public_id=public_id)
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
            kind=user.kind,
        )

    for person in people.values():
        person.organizations = _order_and_dedupe_organizations(person.organizations)
    return sorted(
        people.values(),
        key=lambda person: (person.last_name, person.first_name, person.email),
    )


def get_directory_person(origin, public_id):
    # Rebuild the card for this origin so it still respects distance and opt-outs.
    try:
        return next(iter(get_directory_people(origin, public_id=public_id)))
    except StopIteration:
        raise Http404


def _filter_people(people, form):
    selected_person_key = form.cleaned_data["q"]
    structure_types = set(form.cleaned_data["types"])
    if selected_person_key:
        people = [person for person in people if person.public_id == selected_person_key]
    if structure_types:
        # Match any affiliation, even if another structure is shown first.
        people = [
            person
            for person in people
            if structure_types.intersection(organization.kind for organization in person.organizations)
        ]
    return people


@check_request(can_access_directory)
@readonly_view
def people_results(request, template_name="directory/people_results.html"):
    people = get_directory_people(request.current_organization.coords)
    form = PeopleSearchForm(request.GET, people=people)
    if form.is_valid():
        people = _filter_people(people, form)
    else:
        people = []
    results = pager(people, request.GET.get("page"), items_per_page=settings.PAGE_SIZE_SMALL)
    context = {
        "form": form,
        "results": results,
        "matomo_custom_title": "Annuaire pro - Personnes",
    }
    return render(
        request,
        "directory/includes/people_results.html" if request.htmx else template_name,
        context,
    )


def _person_detail_context(request, person, contact_form=None):
    throttle = MessageThrottle()
    return {
        "person": person,
        "contact_form": contact_form or ContactMessageForm(),
        "rate_limited_message": throttle.limit_message if throttle.is_throttled(request, None) else None,
        "back_url": get_safe_url(
            request,
            "back_url",
            fallback_url=reverse("directory:people_results"),
        ),
        "matomo_custom_title": "Annuaire pro - Fiche personne",
    }


@check_request(can_access_directory)
@readonly_view
def person_detail(request, public_id, template_name="directory/person_detail.html"):
    return render(
        request,
        template_name,
        _person_detail_context(request, get_directory_person(request.current_organization.coords, public_id)),
    )


class MessageThrottle(FailSafeUserRateThrottle):
    scope = "directory-message-user"
    rate = "50/day"

    @property
    def limit_message(self):
        return f"Vous avez atteint la limite de messages envoyés : {self.french_rate_limit(self.rate)}."


@check_request(can_access_directory)
@http_methods(db_write=["POST"])
def send_message(request, public_id):
    person = get_directory_person(request.current_organization.coords, public_id)
    form = ContactMessageForm(request.POST)
    if form.is_valid():
        throttle = MessageThrottle()
        if not throttle.allow_request(request, None):
            form.add_error(None, throttle.limit_message)
        else:
            subject = form.cleaned_data["subject"]
            custom_subject = form.cleaned_data["custom_subject"]
            subject_label = custom_subject if subject == ContactSubject.OTHER else ContactSubject(subject).label
            # Save the contact event, but keep the message body only in the outgoing email.
            ContactMessage.objects.create(
                sender=request.user,
                recipient_id=person.public_id,
                subject=subject,
                custom_subject=custom_subject,
            )
            email = get_email_message(
                to=[person.email],
                context={
                    "sender": request.user,
                    "sender_organization": request.current_organization,
                    "subject": subject_label,
                    "body": form.cleaned_data["body"],
                },
                subject="directory/email/contact_message_subject.txt",
                body="directory/email/contact_message_body.md",
                from_email=formataddr(
                    (f"{request.user.get_full_name()} (via la Plateforme de l’inclusion)", settings.DEFAULT_FROM_EMAIL)
                ),
                reply_to=[request.user.email],
            )
            email.send()
            messages.success(request, "Votre message a bien été envoyé.")
            detail_url = reverse("directory:person_detail", kwargs={"public_id": public_id})
            return redirect(add_url_params(detail_url, {"back_url": get_safe_url(request, "back_url")}))
    return render(request, "directory/person_detail.html", _person_detail_context(request, person, form))
