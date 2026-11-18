"""The job seeker's barriers, gathered from what the platform records, in three columns.

- The pro support reports name the barriers a company identified at the end of a contract. The latest one fills
  « À travailler »; a barrier of the report before it that the latest one no longer names is « Levé ».
- The administrative criteria of the eligibility diagnoses (IAE, and GEIQ for prescribers) hint at barriers:
  shown as signals to confirm, a certified criterion marked as such. Weak hints (ZRR, education level) are left out.
- The pending or accepted orientations towards a service whose data·inclusion thematic matches a barrier put it
  « En cours ». Housing has no barrier of its own in the reports: it goes with the personal or family situation.

Each source keeps the scope of the matching part of the existing job seeker page: the reports the user may read,
the eligibility diagnosis they see there, the orientations of the orientations tab.
"""

import dataclasses

from django.urls import reverse
from django.utils import timezone

from itou.companies.enums import ProSupportReportBarrier
from itou.eligibility.enums import AdministrativeCriteriaKind as Kind
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.insertion.enums import OrientationStatus
from itou.next_steps.models import BarrierStatus, JobSeekerBarrier
from itou.users.perms import can_orient_towards_insertion_service, can_view_pro_support_report
from itou.www.next_steps_views.advisors import visible_orientations


Barrier = ProSupportReportBarrier
OTHER = "OTHER"
NBSP = " "

CRITERIA_BARRIERS = {
    Kind.PM: [Barrier.MOBILITY],
    Kind.TH: [Barrier.HEALTH],
    Kind.AAH: [Barrier.HEALTH, Barrier.FINANCIAL],
    Kind.RSA: [Barrier.FINANCIAL],
    Kind.ASS: [Barrier.FINANCIAL],
    Kind.MINIMA: [Barrier.FINANCIAL],
    Kind.AUTRE_MINIMA: [Barrier.FINANCIAL],
    Kind.PI: [Barrier.FAMILY],
    Kind.ASE: [Barrier.FAMILY],
    Kind.PSH_PR: [Barrier.FAMILY],
    Kind.REF_DA: [Barrier.LEGAL],
    Kind.RS_PS_DA: [Barrier.LEGAL],
    Kind.DETENTION_MJ: [Barrier.LEGAL],
    Kind.FLE: [Barrier.LITERACY],
}

# data·inclusion thematics, by their prefix.
THEMATIC_BARRIERS = {
    "mobilite": Barrier.MOBILITY,
    "sante": Barrier.HEALTH,
    "famille": Barrier.FAMILY,
    "logement-hebergement": Barrier.FAMILY,
    "difficultes-financieres": Barrier.FINANCIAL,
    "equipement-et-alimentation": Barrier.FINANCIAL,
    "numerique": Barrier.DIGITAL,
    "difficultes-administratives-ou-juridiques": Barrier.LEGAL,
    "lecture-ecriture-calcul": Barrier.LITERACY,
}

ONGOING_ORIENTATIONS = [OrientationStatus.PENDING, OrientationStatus.ACCEPTED]

# Remix icons.
BARRIER_ICONS = {
    Barrier.HEALTH: "ri-heart-pulse-line",
    Barrier.MOBILITY: "ri-car-line",
    Barrier.FAMILY: "ri-parent-line",
    Barrier.FINANCIAL: "ri-wallet-3-line",
    Barrier.DIGITAL: "ri-computer-line",
    Barrier.LEGAL: "ri-scales-3-line",
    Barrier.LITERACY: "ri-book-open-line",
    OTHER: "ri-question-line",
}

# The data·inclusion category « Trouver une solution » searches services in.
SEARCH_CATEGORIES = {
    Barrier.MOBILITY: "mobilite",
    Barrier.HEALTH: "sante",
    Barrier.FAMILY: "famille",
    Barrier.FINANCIAL: "difficultes-financieres",
    Barrier.DIGITAL: "numerique",
    Barrier.LEGAL: "difficultes-administratives-ou-juridiques",
    Barrier.LITERACY: "lecture-ecriture-calcul",
}


def _fr(date):
    return f"{timezone.localdate(date):%d/%m/%Y}"


@dataclasses.dataclass
class Clue:
    """Where a barrier comes from."""

    # report, criterion, confirmed (when validating the eligibility), orientation (in progress), lifted.
    kind: str
    text: str
    certified: bool = False
    url: str = ""
    # The reports it comes from, opened in the side drawer: (label, url).
    reports: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class Card:
    key: str
    # In bold; above it, in small, the category when the name is the barrier itself (« Autre frein »).
    name: str
    category: str = ""
    clues: list = dataclasses.field(default_factory=list)
    in_progress: bool = False
    # « Trouver une solution »: the services search for the barrier, around the job seeker.
    search_url: str = ""

    @property
    def icon(self):
        return BARRIER_ICONS[self.key]

    @property
    def to_confirm(self):
        # Only hinted at by the eligibility criteria.
        return all(clue.kind == "criterion" for clue in self.clues)


@dataclasses.dataclass
class Barriers:
    to_work: list
    in_progress: list
    lifted: list
    # The latest report, if any: the section says when it was filled.
    report: object = None

    @property
    def empty(self):
        return not (self.to_work or self.in_progress or self.lifted)


def _reports(request, job_seeker):
    reports = job_seeker.pro_support_reports.select_related("company", "author").order_by("-created_at")
    if request.from_employer:
        reports = reports.filter(company=request.current_organization)
    return [report for report in reports[:2] if can_view_pro_support_report(request, report)]


def _report_text(report):
    by = report.author.get_full_name() if report.author else ""
    if report.company:
        by = f"{by} ({report.company.display_name})" if by else report.company.display_name
    return f"Identifié le {_fr(report.created_at)} dans le bilan d’accompagnement" + (f", par {by}" if by else "")


def _statement_text(statement):
    by = statement.author.get_full_name() if statement.author else ""
    if statement.author_prescriber_organization:
        organization = statement.author_prescriber_organization.display_name
        by = f"{by} ({organization})" if by else organization
    return f"Confirmé le {_fr(statement.created_at)} à la validation de l’éligibilité" + (f", par {by}" if by else "")


def _report_link(job_seeker, report, label):
    return (
        label,
        reverse(
            "next_steps_views:pro_support_report",
            kwargs={"public_id": job_seeker.public_id, "report_id": report.public_id},
        ),
    )


def _search_url(request, job_seeker, key):
    query = {"back_url": reverse("next_steps_views:job_seeker", kwargs={"public_id": job_seeker.public_id})}
    if job_seeker.city_slug:
        query["city"] = job_seeker.city_slug
    if key in SEARCH_CATEGORIES:
        query["category"] = SEARCH_CATEGORIES[key]
    if can_orient_towards_insertion_service(request):
        # As the existing job seeker page does: the search offers to orient this person.
        query["job_seeker_public_id"] = job_seeker.public_id
    return reverse("search:services_results", query=query)


def _diagnoses(request, job_seeker, iae_eligibility_diagnosis):
    """The diagnoses the job seeker page shows the user, with their name."""
    diagnoses = []
    if iae_eligibility_diagnosis:
        diagnoses.append(("IAE", iae_eligibility_diagnosis))
    if request.from_prescriber:
        geiq = GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(job_seeker).first()
        if geiq:
            diagnoses.append(("GEIQ", geiq))
    return diagnoses


def gather_barriers(request, job_seeker, iae_eligibility_diagnosis=None):
    cards = {}

    def card(key):
        if key not in cards:
            cards[key] = Card(key, Barrier(key).label)
        return cards[key]

    reports = _reports(request, job_seeker)
    latest = reports[0] if reports else None
    lifted = []
    if latest:
        latest_link = [_report_link(job_seeker, latest, "Voir le bilan")]
        for key in latest.barriers:
            card(key).clues.append(Clue("report", _report_text(latest), reports=latest_link))
        if latest.other_barrier:
            cards[OTHER] = Card(
                OTHER,
                latest.other_barrier,
                "Autre frein",
                [Clue("report", _report_text(latest), reports=latest_link)],
            )
        if len(reports) > 1:
            previous = reports[1]
            for key in previous.barriers:
                if key not in latest.barriers:
                    lifted.append(
                        Card(
                            key,
                            Barrier(key).label,
                            clues=[
                                Clue(
                                    "lifted",
                                    f"Noté dans le bilan du {_fr(previous.created_at)}, "
                                    f"plus dans celui du {_fr(latest.created_at)}",
                                    reports=[
                                        _report_link(job_seeker, previous, f"Bilan du {_fr(previous.created_at)}"),
                                        _report_link(job_seeker, latest, f"Bilan du {_fr(latest.created_at)}"),
                                    ],
                                )
                            ],
                        )
                    )
    lifted_keys = {lifted_card.key for lifted_card in lifted}

    for name, diagnosis in _diagnoses(request, job_seeker, iae_eligibility_diagnosis):
        for selected in diagnosis.selected_administrative_criteria.select_related("administrative_criteria"):
            criterion = selected.administrative_criteria
            for key in CRITERIA_BARRIERS.get(criterion.kind, []):
                if key in lifted_keys:
                    # The latest report says otherwise, and it is more recent than the criteria.
                    continue
                card(key).clues.append(
                    Clue(
                        "criterion",
                        f"Repéré par le diagnostic d’éligibilité {name} du {_fr(diagnosis.created_at)}{NBSP}: "
                        f"critère «{NBSP}{criterion.name}{NBSP}»",
                        certified=selected.certified_at is not None,
                    )
                )

    # What the professionals stated when validating the eligibility: it prevails over the criteria, and over the
    # latest report when more recent.
    statements = (
        JobSeekerBarrier.objects.filter(job_seeker=job_seeker)
        .select_related("author", "author_prescriber_organization")
        .latest_by_barrier()
    )
    for key, statement in statements.items():
        if latest and latest.created_at > statement.created_at:
            continue
        if key in cards:
            cards[key].clues = [clue for clue in cards[key].clues if clue.kind not in ("criterion", "report")]
        if statement.status == BarrierStatus.CONFIRMED:
            card(key).clues.insert(0, Clue("confirmed", _statement_text(statement)))
            lifted = [lifted_card for lifted_card in lifted if lifted_card.key != key]
            lifted_keys.discard(key)
        elif key in cards and not cards[key].clues:
            del cards[key]

    orientations = (
        visible_orientations(request, job_seeker)
        .filter(status__in=ONGOING_ORIENTATIONS)
        .select_related("service", "sender")
        .prefetch_related("service__thematics")
        .order_by("-created_at")
    )
    for orientation in orientations:
        keys = {
            THEMATIC_BARRIERS[prefix]
            for thematic in orientation.service.thematics.all()
            if (prefix := thematic.value.split("--")[0]) in THEMATIC_BARRIERS
        }
        url = ""
        if orientation.user_can_see_details:
            # Opens in the side drawer of the job seeker page.
            url = reverse(
                "next_steps_views:orientation",
                kwargs={"public_id": job_seeker.public_id, "orientation_id": orientation.pk},
            )
        for key in keys:
            card(key).in_progress = True
            card(key).clues.append(
                Clue(
                    "orientation",
                    f"orientation vers «{NBSP}{orientation.service.name}{NBSP}» le {_fr(orientation.created_at)}"
                    + (f", par {orientation.sender.get_full_name()}" if orientation.sender else "")
                    + f" · {orientation.get_status_display()}",
                    url=url,
                )
            )

    for each in cards.values():
        if any(clue.kind == "report" for clue in each.clues):
            # Named in the latest report: the criteria hinting at it need no confirmation.
            each.clues = [clue for clue in each.clues if clue.kind != "criterion"]

    order = [*Barrier.values, OTHER]
    ordered = sorted(cards.values(), key=lambda card: order.index(card.key))
    to_work = [card for card in ordered if not card.in_progress and card.key not in lifted_keys]
    for card_to_work in to_work:
        card_to_work.search_url = _search_url(request, job_seeker, card_to_work.key)
    return Barriers(
        to_work=to_work,
        in_progress=[card for card in ordered if card.in_progress],
        lifted=[card for card in lifted if card.key not in {c.key for c in ordered if c.in_progress}],
        report=latest,
    )
